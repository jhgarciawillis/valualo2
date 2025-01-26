import streamlit as st 
import pandas as pd
import numpy as np
import joblib
import os
import math
import plotly.graph_objects as go 
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from streamlit.components.v1 import html
import re
import logging
from google.oauth2 import service_account
from googleapiclient.discovery import build
from datetime import datetime
import time

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize geocoder
geolocalizador = Nominatim(user_agent="aplicacion_propiedades")

# Page configuration
st.set_page_config(page_title="Estimador de Valor de Propiedades", layout="wide")

# Basic color scheme
PRIMARY_COLOR = "#1f77b4"  # Blue
SECONDARY_COLOR = "#2ca02c"  # Green

# Enhanced autofill detection JavaScript
autofill_detector = """
<script>
function setupAutofillListener() {
    // Debug flag
    const debug = true;
    
    function debugLog(message) {
        if (debug) console.log('[Autofill Debug]:', message);
    }

    function notifyStreamlit(input, value) {
        debugLog(`Notifying Streamlit of value change: ${input.name} = ${value}`);
        window.parent.postMessage({
            type: 'streamlit:setComponentValue',
            value: value,
            dataType: 'str'
        }, '*');
        
        // Trigger change event
        const event = new Event('change', { bubbles: true });
        input.dispatchEvent(event);
    }

    function monitorInput(input) {
        debugLog(`Setting up monitors for input: ${input.name}`);
        
        // Store initial value
        let lastValue = input.value;
        
        // Monitor for Chrome/Safari autofill
        input.addEventListener('animationstart', (e) => {
            if (e.animationName.includes('autofill') || e.animationName === 'onAutoFillStart') {
                debugLog(`Autofill animation detected on: ${input.name}`);
                if (input.value !== lastValue) {
                    notifyStreamlit(input, input.value);
                    lastValue = input.value;
                }
            }
        });

        // Monitor for Firefox autofill
        input.addEventListener('input', (e) => {
            debugLog(`Input event on: ${input.name}`);
            if (input.value !== lastValue) {
                notifyStreamlit(input, input.value);
                lastValue = input.value;
            }
        });

        // Monitor for Edge/IE autofill
        input.addEventListener('change', (e) => {
            debugLog(`Change event on: ${input.name}`);
            if (input.value !== lastValue) {
                notifyStreamlit(input, input.value);
                lastValue = input.value;
            }
        });

        // Additional check for delayed autofill
        setTimeout(() => {
            if (input.value && input.value !== lastValue) {
                debugLog(`Delayed autofill detected on: ${input.name}`);
                notifyStreamlit(input, input.value);
                lastValue = input.value;
            }
        }, 100);
    }

    // Monitor DOM changes for dynamically added inputs
    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            if (mutation.addedNodes) {
                mutation.addedNodes.forEach((node) => {
                    if (node.tagName === 'INPUT') {
                        monitorInput(node);
                    }
                });
            }
        });
    });

    // Setup initial inputs
    document.querySelectorAll('input').forEach(monitorInput);

    // Watch for new inputs
    observer.observe(document.body, {
        childList: true,
        subtree: true
    });

    debugLog('Autofill listener setup complete');
}

// Setup on DOM ready
if (document.readyState === 'complete') {
    setupAutofillListener();
} else {
    document.addEventListener('DOMContentLoaded', setupAutofillListener);
}
</script>

<style>
/* Chrome/Safari autofill detection */
@keyframes onAutoFillStart {
    from { background-color: transparent; }
    to { background-color: transparent; }
}

@keyframes onAutoFillCancel {
    from { background-color: transparent; }
    to { background-color: transparent; }
}

input:-webkit-autofill {
    animation-name: onAutoFillStart;
    animation-duration: 1ms;
}

input:not(:-webkit-autofill) {
    animation-name: onAutoFillCancel;
    animation-duration: 1ms;
}

/* Firefox autofill styles */
input:-moz-autofill {
    background-color: transparent !important;
}
</style>
"""

# Insert the JavaScript
html(autofill_detector, height=0)

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

# Enhanced text input function with autofill detection
def text_input_with_autofill(label, key, placeholder=""):
    """
    Enhanced text input with cross-browser autofill detection and debugging
    """
    logger.debug(f"Rendering input field - Label: {label}, Key: {key}")
    
    # Remove underscore for session state key
    actual_key = key.replace('_', '')
    
    # Get previous value
    previous_value = st.session_state.get(actual_key, '')
    logger.debug(f"Previous value for {actual_key}: {previous_value}")
    
    # Create input field
    current_value = st.text_input(
        label,
        value=previous_value,
        key=key,
        placeholder=placeholder,
        label_visibility="collapsed"
    )
    
    # Debug current value
    logger.debug(f"Current value for {actual_key}: {current_value}")
    
    # Handle value changes
    if current_value != previous_value:
        logger.debug(f"Value changed in {actual_key}: {previous_value} -> {current_value}")
        st.session_state[actual_key] = current_value
        
        # Check for multiple simultaneous changes (likely autofill)
        if not st.session_state.get('_autofill_batch'):
            st.session_state._autofill_batch = set()
        st.session_state._autofill_batch.add(actual_key)
        
        # If multiple fields changed, trigger rerun
        if len(st.session_state._autofill_batch) > 1:
            logger.debug(f"Multiple fields changed: {st.session_state._autofill_batch}")
            st.session_state._autofill_batch = set()
            st.rerun()
    
    return current_value

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

@st.cache_resource
def cargar_modelos(tipo_propiedad):
    directorio_actual = os.path.dirname(os.path.abspath(__file__))
    prefijo = "renta_" if tipo_propiedad == "Departamento" else ""
    logger.debug(f"Cargando modelos para {tipo_propiedad} con prefijo: '{prefijo}'")
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
            logger.debug(f"Intentando cargar modelo: {nombre_modelo} desde archivo: {ruta_archivo}")
            if os.path.exists(ruta_archivo):
                modelos[nombre_modelo] = joblib.load(ruta_archivo)
                logger.debug(f"Modelo {nombre_modelo} cargado exitosamente")
            else:
                logger.error(f"Archivo de modelo no encontrado: {ruta_archivo}")
                raise FileNotFoundError(f"Archivo de modelo no encontrado: {ruta_archivo}")
    except Exception as e:
        logger.error(f"Error al cargar los modelos: {str(e)}")
        st.error(f"Error al cargar los modelos: {str(e)}. Por favor contacte al soporte.")
    return modelos

def preprocesar_datos(latitud, longitud, terreno, construccion, habitaciones, banos, modelos):
    logger.debug(f"Preprocesando datos para tipo de propiedad: {st.session_state.tipo_propiedad}")
    logger.debug(f"Valores recibidos: terreno={terreno}, construccion={construccion}, habitaciones={habitaciones}, banos={banos}")
    try:
        grupo_ubicacion = agregar_caracteristica_grupo(latitud, longitud, modelos)
        
        # Convert all values to float explicitly
        terreno_val = float(terreno) if terreno is not None else 0.0
        construccion_val = float(construccion) if construccion is not None else 0.0
        habitaciones_val = float(habitaciones) if habitaciones is not None else 0.0
        banos_val = float(banos) if banos is not None else 0.0
        grupo_val = float(grupo_ubicacion) if grupo_ubicacion is not None else 0.0

        datos_entrada = pd.DataFrame({
            'Terreno': [terreno_val],
            'Construccion': [construccion_val],
            'Habitaciones': [habitaciones_val],
            'Banos': [banos_val],
            'GrupoUbicacion': [grupo_val],
        })
        
        logger.debug(f"Datos de entrada antes de imputación: {datos_entrada.to_dict()}")
        datos_imputados = modelos['imputador'].transform(datos_entrada)
        logger.debug(f"Datos después de imputación: {datos_imputados}")
        datos_escalados = modelos['escalador'].transform(datos_imputados)
        logger.debug(f"Datos después de escalado: {datos_escalados}")
        
        return pd.DataFrame(datos_escalados, columns=datos_entrada.columns)
    except Exception as e:
        logger.error(f"Error al preprocesar datos: {str(e)}")
        return None

def predecir_precio(datos_procesados, modelos):
    logger.debug(f"Prediciendo precio para tipo de propiedad: {st.session_state.tipo_propiedad}")
    try:
        precio_bruto = modelos['modelo'].predict(datos_procesados)[0]
        logger.debug(f"Precio bruto predicho: {precio_bruto}")
        
        # Apply 63% adjustment to the raw prediction
        precio_ajustado = precio_bruto * 0.63
        logger.debug(f"Precio ajustado (63%): {precio_ajustado}")
        
        # Round the adjusted price
        precio_redondeado = math.floor(precio_ajustado / 1000) * 1000
        logger.debug(f"Precio redondeado después de ajuste: {precio_redondeado}")

        # Calculate range factors
        factor_escala_bajo = math.exp(-0.05)
        factor_escala_alto = math.exp(0.01 * math.log(precio_redondeado / 1000 + 1))

        # Calculate price ranges
        rango_precio_min = max(0, math.floor((precio_redondeado * factor_escala_bajo) / 1000) * 1000)
        rango_precio_max = math.ceil((precio_redondeado * factor_escala_alto) / 1000) * 1000

        logger.debug(f"Precio final: {precio_redondeado}, Rango: [{rango_precio_min}, {rango_precio_max}]")
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

def initialize_autofill_detection():
    # Initialize session state for batch processing
    if '_autofill_batch' not in st.session_state:
        st.session_state._autofill_batch = set()

# Initialize session state
if 'entrada_direccion' not in st.session_state:
   st.session_state.entrada_direccion = ""
if 'sugerencias' not in st.session_state:
   st.session_state.sugerencias = []
if 'direccion_seleccionada' not in st.session_state:
   st.session_state.direccion_seleccionada = ""
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

# Initialize autofill detection
initialize_autofill_detection()

# Main UI
st.title("Estimador de Valor de Propiedades")

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
        tipo_propiedad = text_input_with_autofill(
            "Tipo de Propiedad",
            key="_tipo_propiedad",
            placeholder="Casa"
        )
        if not tipo_propiedad:
            tipo_propiedad = "Casa"
        st.session_state.tipo_propiedad = tipo_propiedad
        logger.debug(f"Tipo de propiedad seleccionado: {st.session_state.tipo_propiedad}")
            
        modelos = cargar_modelos(st.session_state.tipo_propiedad)
    
    with col2:
        st.markdown(create_tooltip("Dirección de la Propiedad", 
                                 "Ingrese la dirección completa de la propiedad."), 
                   unsafe_allow_html=True)
        
        direccion = text_input_with_autofill(
            "Dirección",
            key="_direccion",
            placeholder="Calle Principal 123, Ciudad de México"
        )
        
        if len(direccion) >= 3 and direccion != st.session_state.get('last_input', ''):
            st.session_state.last_input = direccion
            sugerencias = obtener_sugerencias_direccion(direccion)
            if sugerencias:
                st.session_state.sugerencias = sugerencias
        
        if st.session_state.get('sugerencias'):
            direccion_seleccionada = st.selectbox(
                "Sugerencias de direcciones",
                options=st.session_state.sugerencias,
                label_visibility="collapsed"
            )
            if direccion_seleccionada:
                st.session_state.direccion_seleccionada = direccion_seleccionada

    # Geocodificación (sin mapa)
    if st.session_state.get('direccion_seleccionada'):
        latitud, longitud, ubicacion = geocodificar_direccion(st.session_state.direccion_seleccionada)
        if latitud and longitud:
            st.session_state.latitud = latitud
            st.session_state.longitud = longitud
            st.success(f"Ubicación encontrada: {st.session_state.direccion_seleccionada}")
        else:
            st.error("No se pudo geocodificar la dirección seleccionada.")
    
    # Property details
    st.subheader("Características de la Propiedad")
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown(create_tooltip("Terreno (m²)", 
                                 "Ingrese el área total del terreno en metros cuadrados."), 
                   unsafe_allow_html=True)
        terreno = st.number_input(
            "Metros cuadrados de terreno",
            min_value=0,
            step=1,
            value=int(st.session_state.get('terreno', 0)),
            label_visibility="collapsed"
        )
        if terreno != st.session_state.get('terreno', 0):
            st.session_state.terreno = terreno
            logger.debug(f"Updated terreno to: {terreno}")

    with col2:
        st.markdown(create_tooltip("Construcción (m²)", 
                                 "Ingrese el área construida en metros cuadrados."), 
                   unsafe_allow_html=True)
        construccion = st.number_input(
            "Metros cuadrados de construcción",
            min_value=0,
            step=1,
            value=int(st.session_state.get('construccion', 0)),
            label_visibility="collapsed"
        )
        if construccion != st.session_state.get('construccion', 0):
            st.session_state.construccion = construccion
            logger.debug(f"Updated construccion to: {construccion}")

    with col3:
        st.markdown(create_tooltip("Habitaciones", 
                                 "Ingrese el número total de habitaciones."), 
                   unsafe_allow_html=True)
        habitaciones = st.number_input(
            "Número de habitaciones",
            min_value=0,
            step=1,
            value=int(st.session_state.get('habitaciones', 0)),
            label_visibility="collapsed"
        )
        if habitaciones != st.session_state.get('habitaciones', 0):
            st.session_state.habitaciones = habitaciones
            logger.debug(f"Updated habitaciones to: {habitaciones}")

    with col4:
        st.markdown(create_tooltip("Baños", 
                                 "Ingrese el número de baños."), 
                   unsafe_allow_html=True)
        banos = st.number_input(
            "Número de baños",
            min_value=0.0,
            max_value=10.0,
            step=0.5,
            value=float(st.session_state.get('banos', 0.0)),
            label_visibility="collapsed"
        )
        if banos != st.session_state.get('banos', 0.0):
            st.session_state.banos = banos
            logger.debug(f"Updated banos to: {banos}")

    # Navigation buttons
    st.write("")  # Add spacing before buttons
    if st.button("Siguiente", type="primary"):
        if not st.session_state.get('direccion_seleccionada'):
            st.error("Por favor seleccione una dirección válida.")
        elif terreno == 0 or construccion == 0 or habitaciones == 0 or banos == 0:
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
        nombre = text_input_with_autofill(
            "Nombre",
            key="_nombre",
            placeholder="Ingrese su nombre"
        )

    with col2:
        st.markdown(create_tooltip("Apellido", "Ingrese su apellido."), unsafe_allow_html=True)
        apellido = text_input_with_autofill(
            "Apellido",
            key="_apellido",
            placeholder="Ingrese su apellido"
        )

    col1, col2 = st.columns(2)
    with col1:
        st.markdown(create_tooltip("Correo Electrónico", 
                                "Ingrese su dirección de correo electrónico."), 
                   unsafe_allow_html=True)
        correo = text_input_with_autofill(
            "Correo",
            key="_correo",
            placeholder="usuario@ejemplo.com"
        )

    with col2:
        st.markdown(create_tooltip("Teléfono", "Ingrese su número de teléfono."), 
                   unsafe_allow_html=True)
        telefono = text_input_with_autofill(
            "Teléfono",
            key="_telefono",
            placeholder="9214447277"
        )

    st.subheader("Nivel de Interés")
    interes_options = [
        "Solo estoy explorando el valor de mi propiedad por curiosidad.",
        "Podría considerar vender/alquilar en el futuro.",
        "Estoy interesado/a en vender/alquilar, pero no tengo prisa.",
        "Estoy buscando activamente vender/alquilar mi propiedad.",
        "Necesito vender/alquilar mi propiedad lo antes posible."
    ]
    
    interes_index = 0
    if st.session_state.get('interes_venta') in interes_options:
        interes_index = interes_options.index(st.session_state.interes_venta)
    
    interes_venta = st.radio(
        "",
        options=interes_options,
        index=interes_index,
        label_visibility="collapsed"
    )
    if interes_venta:
        st.session_state.interes_venta = interes_venta
        logger.debug(f"Updated interes_venta to: {interes_venta}")

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
    
    logger.debug("=== VERIFYING VALUES BEFORE PROCESSING ===")
    logger.debug(f"Tipo de propiedad: {st.session_state.tipo_propiedad}")
    logger.debug(f"Terreno: {st.session_state.terreno}")
    logger.debug(f"Construccion: {st.session_state.construccion}")
    logger.debug(f"Habitaciones: {st.session_state.habitaciones}")
    logger.debug(f"Baños: {st.session_state.banos}")
    logger.debug(f"Latitud: {st.session_state.latitud}")
    logger.debug(f"Longitud: {st.session_state.longitud}")
    
    # Load models based on final property type
    modelos = cargar_modelos(st.session_state.tipo_propiedad)
    
    with st.spinner('Calculando...'):
        # Use data from session state for prediction
        datos_procesados = preprocesar_datos(
            st.session_state.latitud, 
            st.session_state.longitud, 
            float(st.session_state.terreno), 
            float(st.session_state.construccion), 
            float(st.session_state.habitaciones), 
            float(st.session_state.banos), 
            modelos
        )
        
        if datos_procesados is not None:
            precio, precio_min, precio_max = predecir_precio(datos_procesados, modelos)
            if precio is not None:
                # Save to Google Sheets with all required data
                data = {
                    'tipo_propiedad': st.session_state.tipo_propiedad,
                    'direccion': st.session_state.direccion_seleccionada,
                    'terreno': st.session_state.terreno,
                    'construccion': st.session_state.construccion,
                    'habitaciones': st.session_state.habitaciones,
                    'banos': st.session_state.banos,
                    'nombre': f"{st.session_state.nombre} {st.session_state.apellido}",
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