import copy
import io
import json
import os

import folium
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from subway_core import (load_graph, load_location, dijkstra, describe,
                         base_name, line_of, LINE_COLORS)

BASE = os.path.dirname(os.path.abspath(__file__))

# 지도 단위별 설정: 폴리곤 json, 지역 코드 키, 이름 키, 기본 데이터 csv
LEVELS = {
    '시도 (전국)': dict(geo='Si_Do_map_utf8.json', key='CTPRVN_CD', name='CTP_KOR_NM',
                    csv='sido.csv', center=[36.0, 127.8], zoom=7, prefix=None),
    '시군구 (전국)': dict(geo='TL_SCCO_SIG_WGS84.json', key='SIG_CD', name='SIG_KOR_NM',
                     csv='Total_People_2018.csv', center=[36.0, 127.8], zoom=7, prefix=None),
    '서울 25개 구': dict(geo='Seoul_Gu_Map.json', key='SIG_CD', name='SIG_KOR_NM',
                     csv='Total_People_2018.csv', center=[37.541, 126.986], zoom=11, prefix='11'),
}
COLORS = ['YlGn', 'YlOrRd', 'Blues', 'BuPu', 'PuRd', 'GnBu', 'OrRd', 'Greens']

st.set_page_config(page_title='지역별 데이터 지도', layout='wide')
st.title('🗺️ 지역별 데이터 지도 (folium 단계구분도)')


@st.cache_data
def load_geo(fname):
    with open(os.path.join(BASE, fname), 'rb') as f:
        raw = f.read()
    for enc in ('utf-8-sig', 'cp949'):          # 원본 json이 euc-kr(cp949)여도 읽히게 처리
        try:
            return json.loads(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    raise ValueError(fname + ' 인코딩을 읽을 수 없습니다.')


def read_csv_bytes(raw):
    for enc in ('utf-8-sig', 'cp949'):
        try:
            return pd.read_csv(io.StringIO(raw.decode(enc)), dtype=str)
        except UnicodeDecodeError:
            continue
    raise ValueError('CSV 인코딩을 읽을 수 없습니다.')


@st.cache_data
def load_subway():
    graph, edges = load_graph()
    return graph, edges, load_location()


@st.cache_data
def load_default(fname):
    df = pd.read_csv(os.path.join(BASE, fname), dtype={'Code': str})
    df['Code'] = df['Code'].str.strip()
    df['Value'] = pd.to_numeric(df['Population'], errors='coerce')
    return df[['Code', 'Value']]


# ---------------- 사이드바 ----------------
with st.sidebar:
    st.header('설정')
    level_name = st.radio('지도 단위', list(LEVELS), index=2)
    cfg = LEVELS[level_name]
    color = st.selectbox('색상 팔레트', COLORS)
    opacity = st.slider('채우기 투명도', 0.2, 1.0, 0.7, 0.1)
    st.divider()
    st.subheader('다른 데이터셋 적용')
    up = st.file_uploader('CSV 업로드 (지역코드 + 숫자 열)', type='csv')
    label = '인구 (명)'
    st.divider()
    st.subheader('🚇 지하철 노선')
    show_sub = st.checkbox('지하철 노선 표시', True)
    sub_lines = st.multiselect('표시할 호선', list(LINE_COLORS), default=list(LINE_COLORS))
    show_st = st.checkbox('역 표시', True)
    use_route = st.checkbox('최단 경로 표시', False)
    s_graph, s_edges, s_loc = load_subway()
    s_names = sorted(s_graph, key=lambda x: (base_name(x), line_of(x)))
    if use_route:
        r_start = st.selectbox('출발역', s_names, index=s_names.index('서울역(1)'))
        r_end = st.selectbox('도착역', s_names, index=s_names.index('강남(2)'))

geo = copy.deepcopy(load_geo(cfg['geo']))

# ---------------- 데이터 준비 ----------------
if up is not None:
    raw = read_csv_bytes(up.getvalue())
    with st.sidebar:
        code_col = st.selectbox('지역코드 열', raw.columns)
        val_col = st.selectbox('값 열', [c for c in raw.columns if c != code_col])
        label = st.text_input('범례 이름', val_col)
    df = pd.DataFrame({'Code': raw[code_col].str.strip(),
                       'Value': pd.to_numeric(raw[val_col].str.replace(',', ''), errors='coerce')})
else:
    df = load_default(cfg['csv'])
    if cfg['csv'] == 'sido.csv':
        label = '값 (예제용 임의 숫자)'

if cfg['prefix']:
    df = df[df['Code'].str.startswith(cfg['prefix'])]
df = df.dropna().drop_duplicates('Code')

if df.empty:
    st.warning('선택한 지도 단위와 맞는 데이터가 없습니다. 지역코드 자릿수(시도 2자리, 시군구 5자리)를 확인하세요.')
    st.stop()

# ---------------- 지도 ----------------
m = folium.Map(location=cfg['center'], zoom_start=cfg['zoom'], tiles='OpenStreetMap')
cp = folium.Choropleth(
    geo_data=geo, name='choropleth', data=df, columns=['Code', 'Value'],
    key_on='feature.properties.' + cfg['key'], fill_color=color,
    fill_opacity=opacity, line_opacity=0.5, nan_fill_color='lightgray',
    legend_name=label,
).add_to(m)

values = df.set_index('Code')['Value']
for feat in cp.geojson.data['features']:
    v = values.get(feat['properties'][cfg['key']])
    feat['properties']['값'] = '데이터 없음' if v is None else '{:,.0f}'.format(v)
folium.GeoJsonTooltip([cfg['name'], '값'], aliases=['지역', label]).add_to(cp.geojson)

# ---- 지하철 노선 겹치기 ----
if show_sub:
    for ln in sub_lines:
        fg = folium.FeatureGroup(name=ln + '호선')
        for a, b, w in s_edges:
            if line_of(a) == ln and line_of(b) == ln:       # 환승 연결(호선이 다른 간선)은 제외
                folium.PolyLine([s_loc[base_name(a)], s_loc[base_name(b)]],
                                color=LINE_COLORS[ln], weight=4, opacity=0.9,
                                tooltip='%s → %s (%d분)' % (base_name(a), base_name(b), w)).add_to(fg)
        if show_st:
            for stn in s_graph:
                if line_of(stn) == ln:
                    folium.CircleMarker(s_loc[base_name(stn)], radius=3, color=LINE_COLORS[ln],
                                        fill=True, fill_color='white', fill_opacity=1,
                                        tooltip=stn).add_to(fg)
        fg.add_to(m)

route_cost, route = None, []
if use_route:
    route_cost, route = dijkstra(s_graph, r_start, r_end)
    if route:
        fg = folium.FeatureGroup(name='최단 경로')
        folium.PolyLine([s_loc[base_name(x)] for x in route], color='#E5231B',
                        weight=7, opacity=0.9).add_to(fg)
        folium.Marker(s_loc[base_name(route[0])], tooltip='출발: ' + route[0],
                      icon=folium.Icon(color='green')).add_to(fg)
        folium.Marker(s_loc[base_name(route[-1])], tooltip='도착: ' + route[-1],
                      icon=folium.Icon(color='red')).add_to(fg)
        fg.add_to(m)

folium.LayerControl().add_to(m)

components.html(m.get_root().render(), height=620)

if use_route:
    if route:
        st.success('%s → %s : 총 %d분 · %d개 역' % (r_start, r_end, route_cost, len(route)))
        with st.expander('경로 자세히 보기'):
            for line in describe(route):
                st.write(line)
    else:
        st.error('경로가 없습니다.')

# ---------------- 표 / 요약 ----------------
names = {f['properties'][cfg['key']]: f['properties'][cfg['name']] for f in geo['features']}
df = df.assign(지역=df['Code'].map(names)).dropna(subset=['지역'])
df = df.sort_values('Value', ascending=False)

c1, c2, c3 = st.columns(3)
c1.metric('지역 수', len(df))
c2.metric('최대', df.iloc[0]['지역'], '{:,.0f}'.format(df.iloc[0]['Value']))
c3.metric('최소', df.iloc[-1]['지역'], '{:,.0f}'.format(df.iloc[-1]['Value']))

t1, t2 = st.tabs(['상위 10개 그래프', '전체 표'])
t1.bar_chart(df.head(10).set_index('지역')['Value'])
t2.dataframe(df[['Code', '지역', 'Value']].rename(columns={'Value': label}), hide_index=True)
