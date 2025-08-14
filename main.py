import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import folium
from streamlit_folium import st_folium
from datetime import datetime, timedelta
import json

# Page configuration
st.set_page_config(
    page_title="Live Flood Data Monitor",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Title and description
st.title("🌊 Live Flood Data Monitor")
st.markdown("""
This app provides real-time flood monitoring data from USGS (United States Geological Survey) 
and other sources, featuring interactive maps and visualizations.
""")

# Sidebar for controls
st.sidebar.header("📊 Data Controls")

# API endpoints and functions
class FloodDataFetcher:
    def __init__(self):
        self.usgs_base_url = "https://waterservices.usgs.gov/nwis/iv/"
        self.rtfi_base_url = "https://api.waterdata.usgs.gov/rtfi-api/v1/"
        
    def fetch_streamflow_data(self, site_codes=None, states=None, period="P1D"):
        """Fetch real-time streamflow data from USGS"""
        params = {
            'format': 'json',
            'parameterCd': '00060',  # Discharge, cubic feet per second
            'period': period,
            'siteStatus': 'active'
        }
        
        if site_codes:
            params['sites'] = ','.join(site_codes)
        elif states:
            params['stateCd'] = ','.join(states)
        else:
            # Default to some major rivers if no specific sites requested
            params['sites'] = '01646500,02231000,07374000,08062500'  # Potomac, St Johns, Mississippi, Trinity
            
        try:
            response = requests.get(self.usgs_base_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            return self.parse_usgs_data(data)
        except requests.exceptions.RequestException as e:
            st.error(f"Error fetching streamflow data: {e}")
            return pd.DataFrame()
    
    def fetch_gage_height_data(self, site_codes=None, states=None, period="P1D"):
        """Fetch real-time gage height data from USGS"""
        params = {
            'format': 'json',
            'parameterCd': '00065',  # Gage height, feet
            'period': period,
            'siteStatus': 'active'
        }
        
        if site_codes:
            params['sites'] = ','.join(site_codes)
        elif states:
            params['stateCd'] = ','.join(states)
        else:
            params['sites'] = '01646500,02231000,07374000,08062500'
            
        try:
            response = requests.get(self.usgs_base_url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            return self.parse_usgs_data(data)
        except requests.exceptions.RequestException as e:
            st.error(f"Error fetching gage height data: {e}")
            return pd.DataFrame()
    
    def parse_usgs_data(self, data):
        """Parse USGS JSON response into pandas DataFrame"""
        if not data.get('value', {}).get('timeSeries'):
            return pd.DataFrame()
            
        records = []
        for series in data['value']['timeSeries']:
            site_info = series['sourceInfo']
            site_code = site_info['siteCode'][0]['value']
            site_name = site_info['siteName']
            latitude = float(site_info['geoLocation']['geogLocation']['latitude'])
            longitude = float(site_info['geoLocation']['geogLocation']['longitude'])
            
            param_info = series['variable']
            param_name = param_info['variableName']
            param_unit = param_info['unit']['unitCode'] if param_info.get('unit') else 'N/A'
            
            for value_data in series['values'][0]['value']:
                if value_data['value'] != '-999999':  # Filter out missing values
                    records.append({
                        'site_code': site_code,
                        'site_name': site_name,
                        'latitude': latitude,
                        'longitude': longitude,
                        'parameter': param_name,
                        'unit': param_unit,
                        'datetime': pd.to_datetime(value_data['dateTime']),
                        'value': float(value_data['value'])
                    })
        
        return pd.DataFrame(records)

# Initialize the data fetcher
@st.cache_data(ttl=300)  # Cache for 5 minutes
def get_flood_data(data_type, period):
    fetcher = FloodDataFetcher()
    if data_type == "Streamflow":
        return fetcher.fetch_streamflow_data(period=period)
    else:
        return fetcher.fetch_gage_height_data(period=period)

# Sidebar controls
data_type = st.sidebar.selectbox(
    "Select Data Type",
    ["Streamflow", "Gage Height"]
)

time_period = st.sidebar.selectbox(
    "Time Period",
    {
        "Last 24 Hours": "P1D",
        "Last 3 Days": "P3D", 
        "Last Week": "P7D",
        "Last 30 Days": "P30D"
    }
)

# Custom site codes input
custom_sites = st.sidebar.text_input(
    "Custom Site Codes (comma-separated)",
    placeholder="01646500,02231000",
    help="Enter USGS site codes separated by commas"
)

# Refresh button
if st.sidebar.button("🔄 Refresh Data"):
    st.cache_data.clear()

# Main content
with st.spinner("Loading flood data..."):
    # Get period code
    period_code = {
        "Last 24 Hours": "P1D",
        "Last 3 Days": "P3D", 
        "Last Week": "P7D",
        "Last 30 Days": "P30D"
    }[time_period]
    
    df = get_flood_data(data_type, period_code)

if df.empty:
    st.warning("No data available for the selected criteria. Please try different parameters.")
    st.stop()

# Data overview
st.subheader("📈 Data Overview")
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Total Sites", len(df['site_code'].unique()))
with col2:
    st.metric("Data Points", len(df))
with col3:
    latest_value = df.groupby('site_code')['value'].last().mean()
    st.metric(f"Avg Current {data_type}", f"{latest_value:.2f}")
with col4:
    st.metric("Last Updated", df['datetime'].max().strftime("%H:%M %m/%d"))

# Interactive map
st.subheader("🗺️ Site Locations Map")

# Get latest data for each site for map display
latest_data = df.groupby('site_code').last().reset_index()

# Create folium map
center_lat = latest_data['latitude'].mean()
center_lon = latest_data['longitude'].mean()
m = folium.Map(location=[center_lat, center_lon], zoom_start=6)

# Add markers for each site
for _, row in latest_data.iterrows():
    # Color code based on current value (simple thresholds)
    value = row['value']
    if data_type == "Streamflow":
        color = 'red' if value > 10000 else 'orange' if value > 5000 else 'green'
    else:  # Gage Height
        color = 'red' if value > 20 else 'orange' if value > 10 else 'green'
    
    folium.Marker(
        [row['latitude'], row['longitude']],
        popup=folium.Popup(f"""
            <b>{row['site_name']}</b><br>
            Site: {row['site_code']}<br>
            Current {data_type}: {value:.2f} {row['unit']}<br>
            Last Updated: {row['datetime'].strftime('%m/%d/%Y %H:%M')}
        """, max_width=250),
        tooltip=f"{row['site_name']}: {value:.2f} {row['unit']}",
        icon=folium.Icon(color=color, icon='tint')
    ).add_to(m)

# Display map
map_data = st_folium(m, width=700, height=500)

# Time series visualization
st.subheader("📊 Time Series Analysis")

# Site selector for detailed view
selected_sites = st.multiselect(
    "Select sites for detailed analysis",
    options=df['site_code'].unique(),
    default=df['site_code'].unique()[:3],  # Default to first 3 sites
    format_func=lambda x: f"{x} - {df[df['site_code']==x]['site_name'].iloc[0]}"
)

if selected_sites:
    # Filter data for selected sites
    filtered_df = df[df['site_code'].isin(selected_sites)]
    
    # Create time series plot
    fig = px.line(
        filtered_df,
        x='datetime',
        y='value',
        color='site_code',
        title=f'{data_type} Over Time',
        labels={
            'datetime': 'Date/Time',
            'value': f'{data_type} ({filtered_df["unit"].iloc[0]})',
            'site_code': 'Site Code'
        }
    )
    
    fig.update_layout(
        height=500,
        hovermode='x unified'
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Statistics table
    st.subheader("📋 Site Statistics")
    stats_df = filtered_df.groupby(['site_code', 'site_name']).agg({
        'value': ['min', 'max', 'mean', 'std', 'count'],
        'latitude': 'first',
        'longitude': 'first'
    }).round(2)
    
    # Flatten column names
    stats_df.columns = ['Min', 'Max', 'Mean', 'Std Dev', 'Data Points', 'Latitude', 'Longitude']
    st.dataframe(stats_df, use_container_width=True)

# Distribution analysis
st.subheader("📈 Value Distribution Analysis")
col1, col2 = st.columns(2)

with col1:
    # Histogram
    fig_hist = px.histogram(
        df,
        x='value',
        nbins=30,
        title=f'{data_type} Distribution',
        labels={'value': f'{data_type} ({df["unit"].iloc[0]})'}
    )
    st.plotly_chart(fig_hist, use_container_width=True)

with col2:
    # Box plot by site
    if len(selected_sites) > 1:
        fig_box = px.box(
            filtered_df,
            x='site_code',
            y='value',
            title=f'{data_type} by Site',
            labels={
                'value': f'{data_type} ({filtered_df["unit"].iloc[0]})',
                'site_code': 'Site Code'
            }
        )
        fig_box.update_xaxes(tickangle=45)
        st.plotly_chart(fig_box, use_container_width=True)
    else:
        st.info("Select multiple sites to see comparison box plot")

# Recent alerts section
st.subheader("⚠️ Potential Flood Conditions")

# Simple flood risk assessment based on thresholds
flood_risks = []
for site_code in df['site_code'].unique():
    site_data = df[df['site_code'] == site_code].sort_values('datetime')
    latest_value = site_data['value'].iloc[-1]
    site_name = site_data['site_name'].iloc[0]
    
    # Simple thresholds (these would be customized per site in production)
    if data_type == "Streamflow":
        if latest_value > 15000:
            risk_level = "HIGH"
            color = "🔴"
        elif latest_value > 8000:
            risk_level = "MODERATE"
            color = "🟡"
        else:
            risk_level = "LOW"
            color = "🟢"
    else:  # Gage Height
        if latest_value > 25:
            risk_level = "HIGH"
            color = "🔴"
        elif latest_value > 15:
            risk_level = "MODERATE" 
            color = "🟡"
        else:
            risk_level = "LOW"
            color = "🟢"
    
    flood_risks.append({
        'Site': f"{site_code} - {site_name}",
        'Current Value': f"{latest_value:.2f} {site_data['unit'].iloc[0]}",
        'Risk Level': f"{color} {risk_level}",
        'Last Updated': site_data['datetime'].iloc[-1].strftime('%m/%d/%Y %H:%M')
    })

risk_df = pd.DataFrame(flood_risks)
st.dataframe(risk_df, use_container_width=True, hide_index=True)

# Footer with data source info
st.markdown("---")
st.markdown("""
**Data Source:** U.S. Geological Survey (USGS) National Water Information System  
**Update Frequency:** Real-time (typically every 15-60 minutes)  
**Disclaimer:** This is a demonstration app. For official flood warnings and emergency information, 
please consult your local emergency management agency and the National Weather Service.
""")

# Add refresh timestamp
st.caption(f"Last refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")