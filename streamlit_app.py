import streamlit as st
import pandas as pd
import numpy as np
import joblib
import os
import math
import plotly.graph_objects as go
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
import folium
from streamlit_folium import folium_static
import re
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(page_title="Estimador de Valor de Propiedades", layout="wide")

# Basic color scheme
PRIMARY_COLOR = "#1f77b4"  # Blue
SECONDARY_COLOR = "#2ca02c"  # Green

# Simple CSS
st.markdown("""
<style>
    .tooltip {
        position: relative;
        display: inline-block;
        margin-left: 5px;
    }
    
    .tooltip .tooltiptext {
        visibility: hidden;
        width: 200px;
        background-color: #f9f9f9;
        border: 1px solid #ddd;
        color: black;
        text-align: center;
        padding: 5px;
        border-radius: 4px;
        position: absolute;
        z-index: 1;
        bottom: 125%;
        left: 50%;
        margin-left: -100px;
        opacity: 0;
        transition: opacity 0.3s;
    }
    
    .tooltip:hover .tooltiptext {
        visibility: visible;
        opacity: 1;
    }
    
    .label-container {
        display: flex;
        align-items: center;
        margin-bottom: 5px;
    }
</style>
""", unsafe_allow_html=True)

# Google Sheets Functions
def get_google_sheets_service():
    credentials = service_account.Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    return build('sheets', 'v4', credentials=credentials)

def save_to_sheets(data):
    try:
        service = get_google_sheets_service()
        spreadsheet_id = st.secrets["spreadsheet"]["id"]
        sheet_name = st.secrets["spreadsheet"]["sheet_name"]
        range_name = f"{sheet_name}!A:L"
        
        # Format timestamp
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Prepare data row
        row = [[
            timestamp,
            data['tipo_propiedad'],
            data['direccion'],
            data['terreno'],
            data['construccion'],
            data['habitaciones'],
            data['banos'],
            data['nombre'],
            data['correo'],
            data['telefono'],
            data['interes_venta'],
            data['precio_estimado']
        ]]
        
        body = {'values': row}
        
        service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption='RAW',
            insertDataOption='INSERT_ROWS',
            body=body
        ).execute()
        
        logger.debug("Data successfully saved to Google Sheets")
        return True
    except Exception as e:
        logger.error(f"Error saving to Google Sheets: {str(e)}")
        return False

# Utility functions
def create_tooltip(label, explanation):
    return f"""
    <div class="label-container">
        {label}
        <div class="tooltip">
            <span>❔</span>
            <span class="tooltiptext">{explanation}</span>
        </div>
    </div>
    """

@st.cache_resource
def cargar_modelos(tipo_propiedad):
    directorio_actual = os.path.dirname(os.path.abspath(__file__))
    prefijo = "renta_" if tipo_propiedad == "Departamento" else ""
    logger.debug(f"Cargando modelos para {tipo_propiedad} con prefijo: {prefijo}")
    modelos = {}
    modelos_requeridos = {
        'modelo': 'bosque_aleatorio.joblib',
        'escalador': 'escalador.joblib',
        'imputador': 'imputador.joblib',
        'agrupamiento': 'agrupamiento.joblib'
    }
    try:
        for nombre_modelo, nombre_archivo in modelos_requeridos.items():
            ruta_archivo = os.path.join(directorio_actual, f"{prefijo}{nombre_archivo}")
            if os.path.exists(ruta_archivo):
                modelos[nombre_modelo] = joblib.load(ruta_archivo)
            else:
                logger.error(f"Archivo de modelo no encontrado: {ruta_archivo}")
                raise FileNotFoundError(f"Archivo de modelo no encontrado: {ruta_archivo}")
    except Exception as e:
        logger.error(f"Error al cargar los modelos: {str(e)}")
        st.error(f"Error al cargar los modelos: {str(e)}. Por favor contacte al soporte.")
    return modelos

# Initialize geocoder
geolocalizador = Nominatim(user_agent="aplicacion_propiedades")

def geocodificar_direccion(direccion):
    logger.debug(f"Intentando geocodificar dirección: {direccion}")
    try:
        ubicacion = geolocalizador.geocode(direccion)
        if ubicacion:
            logger.debug(f"Geocodificación exitosa: {ubicacion.latitude}, {ubicacion.longitude}")
            return ubicacion.latitude, ubicacion.longitude, ubicacion
    except (GeocoderTimedOut, GeocoderUnavailable):
        logger.warning("Servicio de geocodificación no disponible")
    return None, None, None

def obtener_sugerencias_direccion(consulta):
    logger.debug(f"Obteniendo sugerencias para: {consulta}")
    try:
        ubicaciones = geolocalizador.geocode(consulta + ", México", exactly_one=False, limit=5)
        if ubicaciones:
            return [ubicacion.address for ubicacion in ubicaciones]
    except (GeocoderTimedOut, GeocoderUnavailable):
        logger.warning("Servicio de geocodificación no disponible")
    return []

def agregar_caracteristica_grupo(latitud, longitud, modelos):
    logger.debug(f"Agregando característica de grupo para: {latitud}, {longitud}")
    try:
        grupo = modelos['agrupamiento'].predict(pd.DataFrame({'Latitud': [latitud], 'Longitud': [longitud]}))[0]
        logger.debug(f"Grupo obtenido: {grupo}")
        return grupo
    except Exception as e:
        logger.error(f"Error al agregar característica de grupo: {str(e)}")
        return None

def preprocesar_datos(latitud, longitud, terreno, construccion, habitaciones, banos, modelos):
    logger.debug("Preprocesando datos")
    try:
        grupo_ubicacion = agregar_caracteristica_grupo(latitud, longitud, modelos)
        
        datos_entrada = pd.DataFrame({
            'Terreno': [terreno],
            'Construccion': [construccion],
            'Habitaciones': [habitaciones],
            'Banos': [banos],
            'GrupoUbicacion': [grupo_ubicacion],
        })
        
        datos_imputados = modelos['imputador'].transform(datos_entrada)
        datos_escalados = modelos['escalador'].transform(datos_imputados)
        return pd.DataFrame(datos_escalados, columns=datos_entrada.columns)
    except Exception as e:
        logger.error(f"Error al preprocesar datos: {str(e)}")
        return None

def predecir_precio(datos_procesados, modelos):
    logger.debug("Prediciendo precio")
    try:
        precio_bruto = modelos['modelo'].predict(datos_procesados)[0]
        precio_ajustado = precio_bruto
        precio_redondeado = math.floor((precio_ajustado * .63) / 1000) * 1000

        factor_escala_bajo = math.exp(-0.05)
        factor_escala_alto = math.exp(0.01 * math.log(precio_redondeado / 1000 + 1))

        rango_precio_min = max(0, math.floor((precio_redondeado * factor_escala_bajo) / 1000) * 1000)
        rango_precio_max = math.ceil((precio_redondeado * factor_escala_alto) / 1000) * 1000

        return precio_redondeado, rango_precio_min, rango_precio_max
    except Exception as e:
        logger.error(f"Error al predecir el precio: {str(e)}")
        return None, None, None

def validar_correo(correo):
    patron = r'^[\w\.-]+@[\w\.-]+\.\w+$'
    return re.match(patron, correo) is not None

def validar_telefono(telefono):
    patron = r'^\+?[1-9]\d{1,14}$'
    return re.match(patron, telefono) is not None

def on_address_change():
    st.session_state.sugerencias = obtener_sugerencias_direccion(st.session_state.entrada_direccion)
    if st.session_state.sugerencias:
        st.session_state.direccion_seleccionada = st.session_state.sugerencias[0]
    else:
        st.session_state.direccion_seleccionada = ""

# Main UI
st.title("Estimador de Valor de Propiedades")

# Initialize session state
if 'entrada_direccion' not in st.session_state:
   st.session_state.entrada_direccion = ""
if 'sugerencias' not in st.session_state:
   st.session_state.sugerencias = []
if 'direccion_seleccionada' not in st.session_state:
   st.session_state.direccion_seleccionada = ""
if 'mostrar_mapa' not in st.session_state:
   st.session_state.mostrar_mapa = False
if 'last_input' not in st.session_state:
   st.session_state.last_input = ""
if 'step' not in st.session_state:
   st.session_state.step = 1
if 'tipo_propiedad' not in st.session_state:
   st.session_state.tipo_propiedad = "Casa"
if 'terreno' not in st.session_state:
   st.session_state.terreno = 0
if 'construccion' not in st.session_state:
   st.session_state.construccion = 0
if 'habitaciones' not in st.session_state:
   st.session_state.habitaciones = 0
if 'banos' not in st.session_state:
   st.session_state.banos = 0
if 'latitud' not in st.session_state:
   st.session_state.latitud = None
if 'longitud' not in st.session_state:
   st.session_state.longitud = None
if 'nombre' not in st.session_state:
   st.session_state.nombre = ""
if 'apellido' not in st.session_state:
   st.session_state.apellido = ""
if 'correo' not in st.session_state:
   st.session_state.correo = ""
if 'telefono' not in st.session_state:
   st.session_state.telefono = ""
if 'interes_venta' not in st.session_state:
   st.session_state.interes_venta = ""

# Welcome message
st.markdown("""
   <div style='background-color: #f0f2f6; padding: 15px; border-radius: 5px; margin-bottom: 20px;'>
       <h4 style='margin: 0; color: #262730;'>¡Bienvenido a nuestra herramienta gratuita de estimación!</h4>
       <p style='margin: 10px 0 0 0; color: #262730;'>
           Esta herramienta le permite obtener una estimación instantánea y gratuita del valor de su propiedad.<br><br>
           La estimación está basada en los datos de miles de propiedades de todo México.<br><br>
           Favor de llenar todos los campos solicitados para obtener el estimado del valor de la propiedad.
       </p>
   </div>
""", unsafe_allow_html=True)

# Step 1: Property Details
if st.session_state.step == 1:
   st.subheader("Detalles de la Propiedad")
   
   col1, col2 = st.columns(2)
   
   with col1:
       st.markdown(create_tooltip("Tipo de Propiedad", 
                                "Seleccione si es una casa en venta o un departamento en alquiler."), 
                  unsafe_allow_html=True)
       tipo_propiedad = st.selectbox("", ["Casa", "Departamento"])
       st.session_state.tipo_propiedad = tipo_propiedad
       modelos = cargar_modelos(tipo_propiedad)
   
   with col2:
       st.markdown(create_tooltip("Dirección de la Propiedad", 
                                "Ingrese la dirección completa de la propiedad."), 
                  unsafe_allow_html=True)
       
       current_input = st.text_input("", 
                                   key="entrada_direccion",
                                   placeholder="Calle Principal 123, Ciudad de México")
       
       if current_input != st.session_state.last_input and len(current_input) >= 3:
           st.session_state.last_input = current_input
           st.session_state.sugerencias = obtener_sugerencias_direccion(current_input)
           
       if st.session_state.sugerencias:
           direccion_seleccionada = st.selectbox(
               "Sugerencias de direcciones:",
               options=st.session_state.sugerencias,
               key="direccion_dropdown",
               label_visibility="collapsed"
           )
           if direccion_seleccionada:
               st.session_state.direccion_seleccionada = direccion_seleccionada

   # Geocodificación y mapa
   if st.session_state.direccion_seleccionada:
       latitud, longitud, ubicacion = geocodificar_direccion(st.session_state.direccion_seleccionada)
       if latitud and longitud:
           st.session_state.latitud = latitud
           st.session_state.longitud = longitud
           st.success(f"Ubicación encontrada: {st.session_state.direccion_seleccionada}")
           
           if st.button("Mostrar/Ocultar Mapa"):
               st.session_state.mostrar_mapa = not st.session_state.mostrar_mapa

           if st.session_state.mostrar_mapa:
               m = folium.Map(location=[latitud, longitud], zoom_start=15)
               folium.Marker([latitud, longitud], popup=st.session_state.direccion_seleccionada).add_to(m)
               folium_static(m)
       else:
           st.error("No se pudo geocodificar la dirección seleccionada.")

   # Property details
   st.subheader("Características de la Propiedad")
   col1, col2, col3, col4 = st.columns(4)

   with col1:
       st.markdown(create_tooltip("Terreno (m²)", 
                                "Ingrese el área total del terreno en metros cuadrados."), 
                  unsafe_allow_html=True)
       terreno = st.number_input("", min_value=0, step=1, format="%d", key="terreno")
       st.session_state.terreno = terreno

   with col2:
       st.markdown(create_tooltip("Construcción (m²)", 
                                "Ingrese el área construida en metros cuadrados."), 
                  unsafe_allow_html=True)
       construccion = st.number_input("", min_value=0, step=1, format="%d", key="construccion")
       st.session_state.construccion = construccion

   with col3:
       st.markdown(create_tooltip("Habitaciones", 
                                "Ingrese el número total de habitaciones."), 
                  unsafe_allow_html=True)
       habitaciones = st.number_input("", min_value=0, step=1, format="%d", key="habitaciones")
       st.session_state.habitaciones = habitaciones

   with col4:
       st.markdown(create_tooltip("Baños", 
                                "Ingrese el número de baños."), 
                  unsafe_allow_html=True)
       banos = st.number_input("", min_value=0.0, step=0.5, format="%.1f", key="banos")
       st.session_state.banos = banos

   if st.button("Siguiente", type="primary"):
       if not st.session_state.direccion_seleccionada or not terreno or not construccion or not habitaciones or not banos:
           st.error("Por favor complete todos los campos antes de continuar.")
       else:
           st.session_state.step = 2
           st.rerun()

# Step 2: Contact Information
elif st.session_state.step == 2:
   st.subheader("Información de Contacto")
   
   col1, col2 = st.columns(2)
   with col1:
       st.markdown(create_tooltip("Nombre", "Ingrese su nombre."), unsafe_allow_html=True)
       nombre = st.text_input("", key="nombre", placeholder="Ingrese su nombre")
       st.session_state.nombre = nombre

   with col2:
       st.markdown(create_tooltip("Apellido", "Ingrese su apellido."), unsafe_allow_html=True)
       apellido = st.text_input("", key="apellido", placeholder="Ingrese su apellido")
       st.session_state.apellido = apellido

   col1, col2 = st.columns(2)
   with col1:
       st.markdown(create_tooltip("Correo Electrónico", 
                                "Ingrese su dirección de correo electrónico."), 
                  unsafe_allow_html=True)
       correo = st.text_input("", key="correo", placeholder="usuario@ejemplo.com")
       st.session_state.correo = correo

   with col2:
       st.markdown(create_tooltip("Teléfono", "Ingrese su número de teléfono."), 
                  unsafe_allow_html=True)
       telefono = st.text_input("", key="telefono", placeholder="9214447277")
       st.session_state.telefono = telefono

   st.subheader("Nivel de Interés")
   interes_venta = st.selectbox(
       "",
       [
           "Solo estoy explorando el valor de mi propiedad por curiosidad.",
           "Podría considerar vender/alquilar en el futuro.",
           "Estoy interesado/a en vender/alquilar, pero no tengo prisa.",
           "Estoy buscando activamente vender/alquilar mi propiedad.",
           "Necesito vender/alquilar mi propiedad lo antes posible."
       ],
       key="interes_venta"
   )
   st.session_state.interes_venta = interes_venta

   col1, col2 = st.columns(2)
   with col1:
       if st.button("Anterior"):
           st.session_state.step = 1
           st.rerun()
   
   with col2:
       texto_boton = "Estimar Valor" if st.session_state.tipo_propiedad == "Casa" else "Estimar Renta"
       if st.button(texto_boton, type="primary"):
           if not nombre or not apellido:
               st.error("Por favor, ingrese su nombre y apellido.")
           elif not validar_correo(correo):
               st.error("Por favor, ingrese una dirección de correo electrónico válida.")
           elif not validar_telefono(telefono):
               st.error("Por favor, ingrese un número de teléfono válido.")
           elif not interes_venta:
               st.error("Por favor, seleccione su nivel de interés.")
           else:
               st.session_state.step = 3
               st.rerun()

# Step 3: Results
elif st.session_state.step == 3:
   st.subheader("Resultados")
   modelos = cargar_modelos(st.session_state.tipo_propiedad)
   
   with st.spinner('Calculando...'):
       datos_procesados = preprocesar_datos(st.session_state.latitud, st.session_state.longitud, 
                                          st.session_state.terreno, st.session_state.construccion, 
                                          st.session_state.habitaciones, st.session_state.banos, 
                                          modelos)
       if datos_procesados is not None:
           precio, precio_min, precio_max = predecir_precio(datos_procesados, modelos)
           if precio is not None:
               # Save to Google Sheets
               data = {
                   'tipo_propiedad': st.session_state.tipo_propiedad,
                   'direccion': st.session_state.direccion_seleccionada,
                   'terreno': st.session_state.terreno,
                   'construccion': st.session_state.construccion,
                   'habitaciones': st.session_state.habitaciones,
                   'banos': st.session_state.banos,
                   'nombre': st.session_state.nombre,
                   'correo': st.session_state.correo,
                   'telefono': st.session_state.telefono,
                   'interes_venta': st.session_state.interes_venta,
                   'precio_estimado': precio
               }
               
               save_to_sheets(data)
               
               col1, col2 = st.columns(2)
               
               with col1:
                   resultado_texto = "Valor Estimado" if st.session_state.tipo_propiedad == "Casa" else "Renta Mensual Estimada"
                   st.metric(resultado_texto, f"${precio:,}")
                   
               with col2:
                   st.write("Rango Estimado:")
                   st.write(f"Mínimo: ${precio_min:,}")
                   st.write(f"Máximo: ${precio_max:,}")

               fig = go.Figure(go.Bar(
                   x=['Mínimo', 'Estimado', 'Máximo'],
                   y=[precio_min, precio, precio_max],
                   text=[f'${x:,}' for x in [precio_min, precio, precio_max]],
                   textposition='auto',
                   marker_color=[SECONDARY_COLOR, PRIMARY_COLOR, SECONDARY_COLOR]
               ))
               
               fig.update_layout(
                   title='Rango de Precio',
                   yaxis_title='Precio (MXN)',
                   showlegend=False
               )
               st.plotly_chart(fig)

               if st.button("Nueva Estimación"):
                   for key in st.session_state.keys():
                       del st.session_state[key]
                   st.rerun()
           else:
               st.error("Error al calcular el precio. Por favor, intente nuevamente.")
       else:
           st.error("Error al procesar los datos. Por favor, verifique la información ingresada.")