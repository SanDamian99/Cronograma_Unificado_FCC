import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import time, date, datetime
import math
import itertools
from supabase import create_client, Client
import boto3
from io import StringIO

# --- Configuración de la Página ---
st.set_page_config(
    page_title="Cronograma Posgrados",
    page_icon="🗓️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Conexión a Supabase (Base de Datos y Storage) ---
@st.cache_resource
def init_connection():
    # Conexión a la base de datos de Supabase
    db_url = st.secrets["supabase"]["url"]
    db_key = st.secrets["supabase"]["key"]
    supabase_db = create_client(db_url, db_key)

    # Conexión al almacenamiento S3 de Supabase
    s3_endpoint_url = st.secrets["s3"]["endpoint_url"]
    s3_access_key = st.secrets["s3"]["access_key_id"]
    s3_secret_key = st.secrets["s3"]["secret_access_key"]
    s3_region = st.secrets["s3"]["region"]
    
    s3_client = boto3.client(
        's3',
        endpoint_url=s3_endpoint_url,
        aws_access_key_id=s3_access_key,
        aws_secret_access_key=s3_secret_key,
        region_name=s3_region
    )
    
    return supabase_db, s3_client

supabase, s3 = init_connection()

# --- Carga de Datos ---
@st.cache_data(ttl=60)
def load_schedule_data():
    """Carga el cronograma desde la tabla 'cronograma' en Supabase."""
    try:
        response = supabase.table('cronograma').select('*').execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['Fecha'] = pd.to_datetime(df['Fecha']).dt.date
            df['Hora de inicio'] = pd.to_datetime(df['Hora de inicio'], format='%H:%M:%S').dt.time
            df['Hora de finalizacion'] = pd.to_datetime(df['Hora de finalizacion'], format='%H:%M:%S').dt.time
        return df
    except Exception as e:
        st.error(f"Error de conexión con Supabase DB: No se pudo encontrar la tabla 'cronograma'. Detalle: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_s3_csv(bucket_name, file_key):
    """Carga un archivo CSV desde un bucket S3 de Supabase."""
    try:
        response = s3.get_object(Bucket=bucket_name, Key=file_key)
        csv_data = response['Body'].read().decode('utf-8')
        return pd.read_csv(StringIO(csv_data))
    except Exception as e:
        st.error(f"No se pudo cargar el archivo '{file_key}' desde el bucket '{bucket_name}'. Asegúrate de que el archivo exista y las credenciales sean correctas.")
        st.warning(f"Detalle del error: {e}")
        return pd.DataFrame()

# --- Carga Inicial de Datos Externos ---
# Carga los datos de los profesores y del currículo desde S3
professors_df = load_s3_csv('Data_Cronograma', 'profesores.csv')
curriculum_df = load_s3_csv('Data_Cronograma', 'curriculo.csv')

@st.cache_data(ttl=300)
def get_unique_values_from_db(column_name):
    """Obtiene valores únicos para filtros directamente de la base de datos."""
    try:
        response = supabase.table('cronograma').select(column_name).execute()
        if response.data:
            return sorted(list(set(item[column_name] for item in response.data if item[column_name] is not None)))
        return []
    except Exception:
        return []

if 'schedule_df' not in st.session_state:
    st.session_state.schedule_df = load_schedule_data()

# --- Funciones de Validación ---
def check_self_overlap(df):
    """Verifica si hay cruces de horario dentro de las sesiones que se están creando."""
    conflicts = []
    for (idx1, row1), (idx2, row2) in itertools.combinations(df.iterrows(), 2):
        if row1['Fecha'] == row2['Fecha']:
            if row1['Hora de inicio'] < row2['Hora de finalizacion'] and row2['Hora de inicio'] < row1['Hora de finalizacion']:
                conflicts.append(f"🔥 **Cruce Interno:** La sesión {idx1 + 1} y la sesión {idx2 + 1} se solapan el mismo día ({row1['Fecha']}).")
    return conflicts

def check_db_conflicts(new_class_df, existing_df):
    """Verifica conflictos de las nuevas sesiones contra el cronograma ya existente en la base de datos."""
    conflicts = []
    if existing_df.empty:
        return conflicts
    for _, row in new_class_df.iterrows():
        day_schedule = existing_df[existing_df['Fecha'] == row['Fecha']]
        if day_schedule.empty:
            continue
        
        # Conflicto de Profesor
        prof_conflict = day_schedule[
            (day_schedule['Profesor'] == row['Profesor']) &
            (day_schedule['Hora de inicio'] < row['Hora de finalizacion']) &
            (day_schedule['Hora de finalizacion'] > row['Hora de inicio'])
        ]
        if not prof_conflict.empty:
            info = prof_conflict.iloc[0]
            conflicts.append(f"❌ **Cruce de Profesor:** El profesor **{row['Profesor']}** ya tiene la clase **'{info['Nombre de la clase']}'** programada el **{row['Fecha'].strftime('%Y-%m-%d')}** de {info['Hora de inicio'].strftime('%H:%M')} a {info['Hora de finalizacion'].strftime('%H:%M')}.")

        # Conflicto de Estudiantes (si la clase no permite simultaneidad)
        if not row['Simultaneo']:
            student_conflict = day_schedule[
                (day_schedule['Programa'] == row['Programa']) &
                (day_schedule['Semestre'] == row['Semestre']) &
                (day_schedule['Hora de inicio'] < row['Hora de finalizacion']) &
                (day_schedule['Hora de finalizacion'] > row['Hora de inicio']) &
                (day_schedule['Simultaneo'] == False)
            ]
            if not student_conflict.empty:
                info = student_conflict.iloc[0]
                conflicts.append(f"❌ **Cruce de Estudiantes:** El programa **{row['Programa']}** (Sem. {info['Semestre']}) ya tiene la clase **'{info['Nombre de la clase']}'** programada el **{row['Fecha'].strftime('%Y-%m-%d')}** de {info['Hora de inicio'].strftime('%H:%M')} a {info['Hora de finalizacion'].strftime('%H:%M')}.")
    return conflicts

# --- Funciones Auxiliares ---
def format_for_display(df):
    """Formatea el DataFrame para una mejor visualización en Streamlit."""
    df_display = df.copy()
    if 'Fecha' in df_display.columns:
        df_display['Fecha'] = pd.to_datetime(df_display['Fecha']).dt.strftime('%Y-%m-%d')
    for col in ['Hora de inicio', 'Hora de finalizacion']:
        if col in df_display.columns and not df_display[col].empty:
            df_display[col] = df_display[col].apply(lambda x: x.strftime('%H:%M') if pd.notnull(x) else '')
    return df_display

def get_time_options():
    """Genera una lista de opciones de tiempo en intervalos de 30 minutos."""
    times = []
    for hour in range(7, 19): # De 7:00 a 18:30
        times.append(time(hour, 0))
        times.append(time(hour, 30))
    times.append(time(19, 0))
    return times

# --- Inicialización del Estado de la Sesión ---
if 'page_mode' not in st.session_state:
    st.session_state.page_mode = 'select' # 'select' o 'create'
if 'selected_course_info' not in st.session_state:
    st.session_state.selected_course_info = {}
if 'num_sesiones_a_generar' not in st.session_state:
    st.session_state.num_sesiones_a_generar = 1
if 'modulos_a_generar' not in st.session_state:
    st.session_state.modulos_a_generar = [{'num_sesiones': 1}]

# --- INTERFAZ DE USUARIO (UI) ---
st.title("🗓️ Organizador de Cronogramas de Posgrado")

# --- Barra Lateral de Filtros ---
st.sidebar.header("Filtros y Opciones")
programas_list_filter = get_unique_values_from_db('Programa')
profesores_list_filter_db = get_unique_values_from_db('Profesor')
semestres_list_filter = get_unique_values_from_db('Semestre')

st.sidebar.multiselect("Filtrar por Programa", options=programas_list_filter, key="programa_filtro")
st.sidebar.multiselect("Filtrar por Profesor", options=profesores_list_filter_db, key="profesor_filtro")
st.sidebar.multiselect("Filtrar por Semestre", options=semestres_list_filter, format_func=lambda x: f"Semestre {x}", key="semestre_filtro")

# --- PASO 0: SELECCIONAR O CREAR CURSO ---
st.header("➕ Añadir Nueva Clase")

with st.container(border=True):
    st.subheader("Paso 0: Selección de Curso")
    
    action_type = st.radio("¿Qué deseas hacer?", 
                           ["Cargar un curso existente", "Crear un nuevo curso (para electivas)"], 
                           horizontal=True, key="action_type")

    if action_type == "Cargar un curso existente":
        st.session_state.page_mode = 'select'
        if curriculum_df.empty:
            st.error("El archivo de currículo no está disponible. No se pueden cargar cursos existentes.")
        else:
            sel_col1, sel_col2 = st.columns(2)
            # Filtrar programas y semestres del currículo
            programas_curriculo = sorted(curriculum_df['Programa'].unique())
            selected_program = sel_col1.selectbox("Selecciona el Programa", options=programas_curriculo, index=0)
            
            semestres_curriculo = sorted(curriculum_df[curriculum_df['Programa'] == selected_program]['Semestre'].unique())
            selected_semester = sel_col2.selectbox("Selecciona el Semestre", options=semestres_curriculo, index=0)
            
            # Filtrar clases basadas en programa y semestre
            available_classes = curriculum_df[
                (curriculum_df['Programa'] == selected_program) & 
                (curriculum_df['Semestre'] == selected_semester)
            ]
            
            class_options = available_classes['Nombre de la clase'].tolist()
            selected_class_name = st.selectbox("Selecciona la Clase", options=class_options)
            
            if st.button("Cargar Información del Curso"):
                course_data = available_classes[available_classes['Nombre de la clase'] == selected_class_name].iloc[0]
                st.session_state.selected_course_info = course_data.to_dict()
                st.success(f"Información de '{selected_class_name}' cargada correctamente. Continúa en los siguientes pasos.")
                # st.rerun() # Opcional, para refrescar la UI si es necesario
    else:
        st.session_state.page_mode = 'create'
        st.session_state.selected_course_info = {} # Limpiar datos previos
        st.info("Estás en modo de creación. Completa los datos en el Paso 1.")

# --- Formulario Principal ---
# Desactivar los campos si no se ha cargado o se va a crear una clase
is_disabled = st.session_state.page_mode == 'select' and not st.session_state.selected_course_info

with st.container(border=True):
    st.subheader("Paso 1: Datos Generales")
    col1, col2 = st.columns(2)
    with col1:
        nombre_clase = st.text_input("Nombre de la clase", value=st.session_state.selected_course_info.get('Nombre de la clase', ''), disabled=is_disabled)
        programa = st.text_input("Programa", value=st.session_state.selected_course_info.get('Programa', ''), disabled=is_disabled)
        descripcion = st.text_input("Descripción", value=st.session_state.selected_course_info.get('Descripción', 'N/A'))
    with col2:
        catalogo = st.text_input("# de Catalogo", value=st.session_state.selected_course_info.get('# de Catalogo', ''), disabled=is_disabled)
        semestre = st.number_input("Semestre", min_value=1, step=1, format="%d", value=int(st.session_state.selected_course_info.get('Semestre', 1)), disabled=is_disabled)
        creditos = st.number_input("Creditos", min_value=1, step=1, format="%d", value=int(st.session_state.selected_course_info.get('Creditos', 1)), disabled=is_disabled)
        simultaneo = st.checkbox("¿Permite Simultaneidad?", value=st.session_state.selected_course_info.get('Simultaneo', False))

with st.container(border=True):
    st.subheader("Paso 2: Configuración de Sesiones y Requerimientos")
    tipo_clase = st.radio("Tipo de Clase", ["Regular", "Modular"], horizontal=True, key="tipo_clase", disabled=is_disabled)
    
    req_col1, req_col2 = st.columns(2)
    num_estudiantes = req_col1.number_input("Número de estudiantes estimado", min_value=1, step=1, format="%d", value=25, disabled=is_disabled)
    req_espacio = req_col2.text_area("Requerimientos específicos del espacio (opcional)", placeholder="Ej: Video beam, tablero, computadores para 30 personas...", disabled=is_disabled)

    if tipo_clase == "Regular":
        num_sesiones_a_generar = st.number_input("Número de Sesiones a generar", min_value=1, step=1, format="%d", key="num_sesiones_a_generar_input", disabled=is_disabled)
        if st.button("Generar Campos de Sesión"):
            st.session_state.num_sesiones_a_generar = num_sesiones_a_generar
            st.rerun()
    else: # Modular
        num_modulos = st.number_input("Número de Módulos", min_value=1, step=1, format="%d", key="num_modulos_input", disabled=is_disabled)
        if st.button("Generar Módulos"):
            st.session_state.modulos_a_generar = [{'num_sesiones': 1} for _ in range(num_modulos)]
            st.rerun()

# --- Formulario de Sesiones ---
with st.form("new_class_form"):
    st.subheader("Paso 3: Detalles de Fechas, Horarios y Profesores")
    sesiones_data = []
    
    # Preparar lista de profesores desde el archivo S3
    opciones_profesor = ["--- Seleccione un profesor ---"]
    prof_contrato_map = {}
    if not professors_df.empty:
        unique_professors = professors_df.dropna(subset=['Profesor', 'Contrato']).drop_duplicates(subset=['Profesor'])
        opciones_profesor += sorted(unique_professors['Profesor'].tolist())
        prof_contrato_map = pd.Series(unique_professors.Contrato.values, index=unique_professors.Profesor).to_dict()

    # Límites de fechas
    min_date = date(2026, 1, 13)
    max_date = date(2026, 6, 26)
    
    if st.session_state.tipo_clase == "Regular":
        st.markdown("##### Profesor (asignado a todas las sesiones)")
        profesor_existente_reg = st.selectbox("Profesor Existente", options=opciones_profesor, help="Selecciona un profesor de la lista.")
        profesor_regular = profesor_existente_reg if profesor_existente_reg != "--- Seleccione un profesor ---" else ""
        tipo_contrato_regular = prof_contrato_map.get(profesor_regular, "No especificado")
        if profesor_regular:
            st.info(f"Tipo de Contrato: **{tipo_contrato_regular}**")
        
        st.markdown("---")
        for i in range(st.session_state.get('num_sesiones_a_generar', 1)):
            st.markdown(f"**Sesión {i + 1}**")
            s_col1, s_col2, s_col3 = st.columns(3)
            fecha = s_col1.date_input("Fecha", value=min_date, min_value=min_date, max_value=max_date, key=f"reg_date_{i}")
            hora_inicio = s_col2.selectbox("Inicio", options=get_time_options(), index=2, format_func=lambda t: t.strftime('%H:%M'), key=f"reg_start_{i}") # 8:00 AM
            duracion = s_col3.number_input("Duración (horas enteras)", min_value=1, step=1, value=2, key=f"reg_dur_{i}")
            
            # Calcular hora de fin y validar
            hora_fin = (datetime.combine(date.today(), hora_inicio) + pd.Timedelta(hours=duracion)).time()
            if hora_fin > time(19, 0):
                st.warning(f"La duración hace que la clase termine después de las 7:00 PM. Ajusta la hora de inicio o la duración.")

            sesiones_data.append({"Profesor": profesor_regular, "Tipo de Contrato": tipo_contrato_regular, "Módulo": 1, "Sesión": i + 1, "Fecha": fecha, "Hora de inicio": hora_inicio, "Hora de finalizacion": hora_fin})
    else: # Modular
        sesion_counter = 1
        for i, mod in enumerate(st.session_state.get('modulos_a_generar', [])):
            st.markdown(f"--- \n ### Módulo {i + 1}")
            profesor_existente_mod = st.selectbox(f"Profesor Existente (M{i+1})", options=opciones_profesor, key=f"prof_existente_mod_{i}", help="Selecciona un profesor para este módulo.")
            profesor_modulo = profesor_existente_mod if profesor_existente_mod != "--- Seleccione un profesor ---" else ""
            tipo_contrato_modulo = prof_contrato_map.get(profesor_modulo, "No especificado")
            if profesor_modulo:
                st.info(f"Tipo de Contrato: **{tipo_contrato_modulo}**")

            num_sesiones_mod = st.number_input(f"Sesiones para Módulo {i + 1}", min_value=1, step=1, format="%d", value=mod['num_sesiones'], key=f"ses_num_mod_form_{i}")
            
            for j in range(num_sesiones_mod):
                st.markdown(f"**Sesión {j + 1} del Módulo {i + 1}**")
                ms_col1, ms_col2, ms_col3 = st.columns(3)
                fecha = ms_col1.date_input("Fecha", value=min_date, min_value=min_date, max_value=max_date, key=f"mod_date_{i}_{j}")
                hora_inicio = ms_col2.selectbox("Inicio", options=get_time_options(), index=2, format_func=lambda t: t.strftime('%H:%M'), key=f"mod_start_{i}_{j}")
                duracion = ms_col3.number_input("Duración (horas enteras)", min_value=1, step=1, value=2, key=f"mod_dur_{i}_{j}")
                
                hora_fin = (datetime.combine(date.today(), hora_inicio) + pd.Timedelta(hours=duracion)).time()
                if hora_fin > time(19, 0):
                    st.warning(f"La duración hace que la clase termine después de las 7:00 PM.")

                sesiones_data.append({"Profesor": profesor_modulo, "Tipo de Contrato": tipo_contrato_modulo, "Módulo": i + 1, "Sesión": sesion_counter, "Fecha": fecha, "Hora de inicio": hora_inicio, "Hora de finalizacion": hora_fin})
                sesion_counter += 1

    submit_button = st.form_submit_button("Añadir Clase al Cronograma", disabled=is_disabled)

if submit_button:
    # --- Lógica de Envío del Formulario ---
    if not all([descripcion, catalogo, nombre_clase, programa]):
        st.error("Por favor, completa todos los campos de 'Datos Generales' antes de añadir la clase.")
    elif any(s['Hora de finalizacion'] > time(19, 0) for s in sesiones_data):
        st.error("Error: Una o más sesiones terminan después de las 7:00 PM. Por favor, ajusta los horarios.")
    elif any(not s['Profesor'] for s in sesiones_data):
        st.error("Error: Todas las sesiones o módulos deben tener un profesor seleccionado de la lista.")
    else:
        temp_df = pd.DataFrame(sesiones_data)
        self_conflicts = check_self_overlap(temp_df)
        if self_conflicts:
            st.error("No se pudo añadir. Se encontraron cruces entre las sesiones que intentas registrar:")
            for c in self_conflicts: st.warning(c)
        else:
            records = [{
                'ID': f"{catalogo}-{nombre_clase.replace(' ', '')[:5]}-S{s['Sesión']}",
                'Descripción': descripcion,
                '# de Catalogo': catalogo,
                'Nombre de la clase': nombre_clase,
                'Programa': programa,
                'Semestre': int(semestre),
                'Creditos': int(creditos),
                'Profesor': s['Profesor'],
                'Tipo de Contrato': s['Tipo de Contrato'],
                'Simultaneo': simultaneo,
                'Estudiantes Estimados': int(num_estudiantes),
                'Requerimientos Espacio': req_espacio,
                'Módulo': s['Módulo'],
                'Sesión': s['Sesión'],
                'Fecha': s['Fecha'],
                'Hora de inicio': s['Hora de inicio'],
                'Hora de finalizacion': s['Hora de finalizacion']
            } for s in sesiones_data]
            
            final_df = pd.DataFrame(records)
            db_conflicts = check_db_conflicts(final_df, st.session_state.schedule_df)
            
            if db_conflicts:
                st.error("No se pudo añadir. Se encontraron conflictos con el cronograma existente:")
                for c in db_conflicts: st.warning(c)
            else:
                # Convertir a string para la inserción en Supabase
                final_df['Fecha'] = final_df['Fecha'].astype(str)
                final_df['Hora de inicio'] = final_df['Hora de inicio'].astype(str)
                final_df['Hora de finalizacion'] = final_df['Hora de finalizacion'].astype(str)
                
                try:
                    supabase.table('cronograma').insert(final_df.to_dict('records')).execute()
                    st.success(f"¡Clase '{nombre_clase}' añadida exitosamente!")
                    st.cache_data.clear() # Limpiar caché para recargar los datos
                    st.session_state.schedule_df = load_schedule_data()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al guardar en la base de datos: {e}")

# --- Visualización del Cronograma y Eliminación ---
st.markdown("---")
st.header("📅 Cronograma General de Clases")

if st.session_state.schedule_df.empty:
    st.info("Aún no se han añadido clases al cronograma.")
else:
    # Aplicar filtros
    filtered_df = st.session_state.schedule_df.copy()
    if st.session_state.programa_filtro: filtered_df = filtered_df[filtered_df['Programa'].isin(st.session_state.programa_filtro)]
    if st.session_state.profesor_filtro: filtered_df = filtered_df[filtered_df['Profesor'].isin(st.session_state.profesor_filtro)]
    if st.session_state.semestre_filtro: filtered_df = filtered_df[filtered_df['Semestre'].isin(st.session_state.semestre_filtro)]
    
    st.dataframe(format_for_display(filtered_df.sort_values(by="Fecha")), width='stretch')
    
    # Botones de descarga
    completo_csv = st.session_state.schedule_df.to_csv(index=False).encode('utf-8')
    filtrado_csv = filtered_df.to_csv(index=False).encode('utf-8')
    d_col1, d_col2 = st.columns(2)
    d_col1.download_button("📥 Descargar Cronograma Completo (CSV)", completo_csv, 'cronograma_completo.csv', 'text/csv')
    d_col2.download_button("📥 Descargar Vista Filtrada (CSV)", filtrado_csv, 'cronograma_filtrado.csv', 'text/csv')
    
    # --- Visualizaciones Gráficas ---
    st.markdown("---")
    st.header("📊 Visualizaciones del Cronograma")

    if not filtered_df.empty:
        # Preparar datos para gráficos
        df_for_plot = filtered_df.copy()
        df_for_plot['start'] = df_for_plot.apply(lambda row: pd.to_datetime(f"{row['Fecha']} {row['Hora de inicio']}"), axis=1)
        df_for_plot['end'] = df_for_plot.apply(lambda row: pd.to_datetime(f"{row['Fecha']} {row['Hora de finalizacion']}"), axis=1)

        # Gráfico de Línea de Tiempo (Timeline)
        st.subheader("🗓️ Vista de Calendario (Timeline)")
        fig_timeline = px.timeline(
            df_for_plot.sort_values(by="start"), 
            x_start="start", x_end="end", y="Programa", 
            color="Profesor", text="Nombre de la clase",
            hover_data=['ID', 'Semestre', 'Módulo', 'Fecha'],
            title="Cronograma de Clases por Programa y Profesor"
        )
        fig_timeline.update_layout(
            xaxis_title="Fecha y Hora", yaxis_title="Programa",
            plot_bgcolor='#262730', paper_bgcolor='#0E1117',
            font_color='white', title_font_color='#D4AF37'
        )
        st.plotly_chart(fig_timeline, width='stretch')
        
        # Diagrama de Gantt
        st.subheader("📊 Diagrama de Gantt por Clase")
        fig_gantt = px.timeline(
            df_for_plot.sort_values(by="start"),
            x_start="start", x_end="end", y="Nombre de la clase",
            color="Programa",
            title="Duración de Clases Individuales",
            hover_data=['Profesor', 'Semestre']
        )
        fig_gantt.update_layout(
            xaxis_title="Fecha", yaxis_title="Clase",
            plot_bgcolor='#262730', paper_bgcolor='#0E1117',
            font_color='white', title_font_color='#D4AF37'
        )
        st.plotly_chart(fig_gantt, width='stretch')

    else:
        st.warning("No hay datos para mostrar en las visualizaciones con los filtros actuales.")

    # --- Sección de Eliminación ---
    st.markdown("---")
    st.header("🗑️ Eliminar Clase del Cronograma")
    with st.form("delete_form"):
        # Usar una combinación de Nombre, Catálogo y Programa para identificar una clase de forma única
        unique_classes = st.session_state.schedule_df[['Nombre de la clase', '# de Catalogo', 'Programa']].drop_duplicates()
        class_options_delete = [f"{row['Nombre de la clase']} ({row['# de Catalogo']} - {row['Programa']})" for index, row in unique_classes.iterrows()]
        
        class_to_delete_display = st.selectbox("Selecciona la clase a eliminar", options=sorted(class_options_delete))
        
        if st.form_submit_button("Eliminar Clase"):
            if class_to_delete_display:
                # Extraer el # de Catalogo para identificar la clase a eliminar
                catalogo_to_delete = class_to_delete_display.split('(')[1].split(' - ')[0]
                
                try:
                    # El ID base se deriva del # de Catalogo. Eliminamos todas las sesiones que coincidan.
                    supabase.table('cronograma').delete().like('ID', f'{catalogo_to_delete}%').execute()
                    st.success(f"La clase con catálogo '{catalogo_to_delete}' ha sido eliminada.")
                    st.cache_data.clear()
                    st.session_state.schedule_df = load_schedule_data()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al eliminar de la base de datos: {e}")
