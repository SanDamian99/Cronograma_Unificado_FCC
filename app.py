import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import time, date, datetime
import itertools
from supabase import create_client, Client
import boto3
from io import StringIO, BytesIO

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

# --- Utilidades de lectura desde S3 ---
@st.cache_data(ttl=300)
def load_s3_csv(bucket_name, file_key):
    """Carga un archivo CSV desde un bucket S3, manejando múltiples codificaciones."""
    try:
        response = s3.get_object(Bucket=bucket_name, Key=file_key)
        csv_bytes = response['Body'].read()
        try:
            csv_data = csv_bytes.decode('utf-8')
        except UnicodeDecodeError:
            st.warning(f"El archivo '{file_key}' no es UTF-8. Intentando con 'latin-1'.")
            csv_data = csv_bytes.decode('latin-1')
        return pd.read_csv(StringIO(csv_data))
    except Exception as e:
        st.error(f"No se pudo cargar o procesar el archivo '{file_key}' desde S3.")
        st.warning(f"Detalle del error: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def load_s3_excel(bucket_name, file_key, sheet_name=0):
    """Carga un Excel (.xlsx) desde un bucket S3."""
    try:
        response = s3.get_object(Bucket=bucket_name, Key=file_key)
        data = response['Body'].read()
        try:
            df = pd.read_excel(BytesIO(data), sheet_name=sheet_name)  # requiere openpyxl
        except Exception as e:
            st.error("Error leyendo el Excel. Asegúrate de tener 'openpyxl' instalado en el entorno.")
            st.warning(f"Detalle: {e}")
            return pd.DataFrame()
        return df
    except Exception as e:
        st.error(f"No se pudo cargar el Excel '{file_key}' desde S3.")
        st.warning(f"Detalle del error: {e}")
        return pd.DataFrame()

# --- Carga Inicial de Datos Externos ---
professors_df = load_s3_csv('Data_Cronograma', 'profesores.csv')
raw_curriculum_df = load_s3_excel('Data_Cronograma', 'PROGRAMACION_Postgrado_v1.xlsx')

# --- Normalización del currículo a los nombres esperados por la UI ---
def parse_time_safe(val):
    if pd.isna(val):
        return None
    try:
        return pd.to_datetime(str(val)).time()
    except Exception:
        try:
            return pd.to_datetime(str(val), format='%H:%M').time()
        except Exception:
            return None

def normalize_curriculum_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    d = df.copy()

    # Fechas y horas
    if 'F Reunión' in d.columns:
        if not pd.api.types.is_datetime64_any_dtype(d['F Reunión']):
            d['F Reunión'] = pd.to_datetime(d['F Reunión'], errors='coerce')
    else:
        d['F Reunión'] = pd.NaT

    d['Hora Inicio'] = d['Hora Inicio'].apply(parse_time_safe) if 'Hora Inicio' in d.columns else None
    d['Hora Final']  = d['Hora Final'].apply(parse_time_safe)  if 'Hora Final'  in d.columns else None

    # Renombres para la UI/DB
    rename_map = {
        'Nombre del curso': 'Nombre de la clase',
        'Catálogo': '# de Catalogo',
        'No.Creditos': 'Creditos',
    }
    for src, dst in rename_map.items():
        if src in d.columns:
            d[dst] = d[src]

    # Descripción
    if 'Descripción Materia' in d.columns:
        d['Descripción_UI'] = d['Descripción Materia'].fillna('')
    elif 'Descripción' in d.columns:
        d['Descripción_UI'] = d['Descripción'].fillna('')
    else:
        d['Descripción_UI'] = ''

    # Tipos
    if 'Semestre' in d.columns:
        d['Semestre'] = pd.to_numeric(d['Semestre'], errors='coerce').astype('Int64').astype('float').fillna(0).astype(int)
    if 'Creditos' in d.columns:
        d['Creditos'] = pd.to_numeric(d['Creditos'], errors='coerce').fillna(0).astype(int)
    if '# de Catalogo' in d.columns:
        d['# de Catalogo'] = d['# de Catalogo'].astype(str)
    if 'Programa' in d.columns:
        d['Programa'] = d['Programa'].astype(str)
    if 'Nombre profesor' in d.columns:
        d['Nombre profesor'] = d['Nombre profesor'].fillna('')

    return d

curriculum_df = normalize_curriculum_df(raw_curriculum_df)

# --- Catálogo de contratos permitido (desde profesores.csv) ---
contratos_opciones = []
if not professors_df.empty and 'Contrato' in professors_df.columns:
    contratos_opciones = sorted(
        professors_df['Contrato']
        .dropna()
        .astype(str)
        .str.strip()
        .unique()
        .tolist()
    )

# --- Fechas del semestre (FIJAS) ---
SEMESTRE_INICIO = date(2026, 1, 13)
SEMESTRE_FIN    = date(2026, 6, 29)
min_date, max_date = SEMESTRE_INICIO, SEMESTRE_FIN

# --- Carga de cronograma desde DB ---
@st.cache_data(ttl=60)
def load_schedule_data():
    """Carga el cronograma desde la tabla 'cronograma' en Supabase."""
    try:
        response = supabase.table('cronograma').select('*').execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['Fecha'] = pd.to_datetime(df['Fecha']).dt.date
            df['Hora de inicio'] = pd.to_datetime(df['Hora de inicio'], format='%H:%M:%S', errors='coerce').dt.time
            df['Hora de finalizacion'] = pd.to_datetime(df['Hora de finalizacion'], format='%H:%M:%S', errors='coerce').dt.time
        return df
    except Exception as e:
        st.error(f"Error de conexión con Supabase DB: No se pudo encontrar la tabla 'cronograma'. Detalle: {e}")
        return pd.DataFrame()

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
            if (row1['Hora de inicio'] < row2['Hora de finalizacion']) and (row2['Hora de inicio'] < row1['Hora de finalizacion']):
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
            conflicts.append(
                f"❌ **Cruce de Profesor:** El profesor **{row['Profesor']}** ya tiene la clase **'{info['Nombre de la clase']}'** "
                f"el **{row['Fecha'].strftime('%Y-%m-%d')}** de {info['Hora de inicio'].strftime('%H:%M')} a {info['Hora de finalizacion'].strftime('%H:%M')}."
            )

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
                conflicts.append(
                    f"❌ **Cruce de Estudiantes:** El programa **{row['Programa']}** (Sem. {info['Semestre']}) ya tiene la clase "
                    f"**'{info['Nombre de la clase']}'** el **{row['Fecha'].strftime('%Y-%m-%d')}** de "
                    f"{info['Hora de inicio'].strftime('%H:%M')} a {info['Hora de finalizacion'].strftime('%H:%M')}."
                )
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
    for hour in range(7, 19):  # 7:00 a 18:30
        times.append(time(hour, 0))
        times.append(time(hour, 30))
    times.append(time(19, 0))
    return times

# --- Inicialización del Estado de la Sesión ---
if 'page_mode' not in st.session_state:
    st.session_state.page_mode = 'select'  # 'select' o 'create'
if 'selected_course_info' not in st.session_state:
    st.session_state.selected_course_info = {}
if 'num_sesiones_a_generar' not in st.session_state:
    st.session_state.num_sesiones_a_generar = 1
if 'modulos_a_generar' not in st.session_state:
    st.session_state.modulos_a_generar = [{'num_sesiones': 1}]
if 'prefill_sesiones' not in st.session_state:
    st.session_state.prefill_sesiones = []
if 'prefill_profesor' not in st.session_state:
    st.session_state.prefill_profesor = ""

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

    action_type = st.radio(
        "¿Qué deseas hacer?",
        ["Cargar un curso existente", "Crear un nuevo curso (para electivas)"],
        horizontal=True, key="action_type"
    )

    if action_type == "Cargar un curso existente":
        st.session_state.page_mode = 'select'
        if curriculum_df.empty:
            st.error("El archivo de currículo no está disponible. No se pueden cargar cursos existentes.")
        else:
            sel_col1, sel_col2 = st.columns(2)
            # Programas y semestres del currículo
            programas_curriculo = sorted(curriculum_df['Programa'].dropna().unique())
            selected_program = sel_col1.selectbox("Selecciona el Programa", options=programas_curriculo, index=0)

            semestres_curriculo = sorted(curriculum_df[curriculum_df['Programa'] == selected_program]['Semestre'].dropna().unique())
            if len(semestres_curriculo) == 0:
                st.warning("El programa seleccionado no tiene semestres disponibles en el Excel.")
                semestres_curriculo = [1]
            selected_semester = sel_col2.selectbox("Selecciona el Semestre", options=semestres_curriculo, index=0)

            # Filtrado de clases
            filtered = curriculum_df[
                (curriculum_df['Programa'] == selected_program) &
                (curriculum_df['Semestre'] == int(selected_semester))
            ].copy()

            if filtered.empty:
                st.warning("No hay filas para el programa/semestre seleccionados.")
            else:
                # Opciones únicas por (Nombre, #Catálogo)
                unique_classes = (
                    filtered[['Nombre de la clase', '# de Catalogo']]
                    .dropna()
                    .drop_duplicates()
                    .sort_values(by=['Nombre de la clase', '# de Catalogo'])
                )
                unique_classes['label'] = unique_classes.apply(
                    lambda r: f"{r['Nombre de la clase']} (Catálogo {r['# de Catalogo']})", axis=1
                )
                class_labels = unique_classes['label'].tolist()
                selected_label = st.selectbox("Selecciona la Clase", options=class_labels)

                if st.button("Cargar Información del Curso"):
                    sel_row = unique_classes[unique_classes['label'] == selected_label].iloc[0]
                    # Todas las filas de ese curso para prefill de sesiones
                    course_rows = filtered[
                        (filtered['Nombre de la clase'] == sel_row['Nombre de la clase']) &
                        (filtered['# de Catalogo'] == sel_row['# de Catalogo'])
                    ].copy()

                    # Prefill profesor (más frecuente)
                    prefill_prof = ""
                    if 'Nombre profesor' in course_rows.columns:
                        vc = course_rows['Nombre profesor'].replace('', pd.NA).dropna()
                        if not vc.empty:
                            prefill_prof = vc.value_counts().idxmax()

                    # Prefill contrato (si Excel trae Descripción.2)
                    prefill_contrato = ""
                    if 'Descripción.2' in course_rows.columns:
                        cc = course_rows['Descripción.2'].replace('', pd.NA).dropna()
                        if not cc.empty:
                            prefill_contrato = str(cc.value_counts().idxmax()).strip()

                    # Prefill sesiones desde F Reunión, Hora Inicio/Final (acotadas al semestre fijo)
                    sessions = []
                    course_rows = course_rows.sort_values(by='F Reunión')
                    for _, r in course_rows.iterrows():
                        fecha_raw = None if pd.isna(r['F Reunión']) else r['F Reunión'].date()
                        if fecha_raw is None:
                            continue
                        # Acotar a los límites del semestre
                        fecha = min(max(fecha_raw, min_date), max_date)
                        hi = r['Hora Inicio'] if pd.notna(r['Hora Inicio']) else None
                        hf = r['Hora Final'] if pd.notna(r['Hora Final']) else None
                        if (hi is not None) and (hf is not None):
                            dur = datetime.combine(date.today(), hf) - datetime.combine(date.today(), hi)
                            dur_horas = max(1, int(round(dur.total_seconds() / 3600)))
                        else:
                            dur_horas = 2
                        sessions.append({
                            "Fecha": fecha,
                            "Hora de inicio": hi if hi else time(8, 0),
                            "Hora de finalizacion": hf if hf else time(10, 0),
                            "Duracion": dur_horas
                        })

                    if len(sessions) == 0:
                        sessions = [{
                            "Fecha": min_date,
                            "Hora de inicio": time(8, 0),
                            "Hora de finalizacion": time(10, 0),
                            "Duracion": 2
                        }]

                    # Centro de costo (primero no nulo)
                    centro_costo_val = None
                    if 'Centro_costo_programa' in course_rows.columns:
                        cc_series = course_rows['Centro_costo_programa'].dropna()
                        if not cc_series.empty:
                            try:
                                centro_costo_val = int(cc_series.iloc[0])
                            except Exception:
                                centro_costo_val = None

                    st.session_state.prefill_sesiones = sessions
                    st.session_state.num_sesiones_a_generar = len(sessions)
                    st.session_state.prefill_profesor = prefill_prof

                    st.session_state.selected_course_info = {
                        'Nombre de la clase': sel_row['Nombre de la clase'],
                        'Programa': selected_program,
                        'Descripción': (course_rows['Descripción_UI'].dropna().iloc[0]
                                        if 'Descripción_UI' in course_rows.columns and not course_rows['Descripción_UI'].dropna().empty
                                        else 'N/A'),
                        '# de Catalogo': str(sel_row['# de Catalogo']),
                        'Semestre': int(selected_semester),
                        'Creditos': int(course_rows['Creditos'].dropna().iloc[0]) if 'Creditos' in course_rows.columns and not course_rows['Creditos'].dropna().empty else 1,
                        'Simultaneo': False,
                        'Centro_costo_programa': centro_costo_val,
                        'Contrato_prefill': prefill_contrato
                    }
                    st.success(f"Información de '{sel_row['Nombre de la clase']}' cargada. Prefill de {len(sessions)} sesión(es).")
    else:
        st.session_state.page_mode = 'create'
        st.session_state.selected_course_info = {}
        st.session_state.prefill_sesiones = []
        st.session_state.prefill_profesor = ""
        st.info("Estás en modo de creación. Completa los datos en el Paso 1.")

# --- Formulario Principal ---
readonly_from_excel = st.session_state.page_mode == 'select' and bool(st.session_state.selected_course_info)
is_disabled_for_empty_select = st.session_state.page_mode == 'select' and not st.session_state.selected_course_info

with st.container(border=True):
    st.subheader("Paso 1: Datos Generales")
    if readonly_from_excel:
        st.caption("🔒 Campos bloqueados (Origen: Excel): Programa, Semestre, Créditos y # de Catálogo.")

    col1, col2 = st.columns(2)
    with col1:
        # Nombre editable (puedes bloquearlo si lo prefieres)
        nombre_clase = st.text_input(
            "Nombre de la clase",
            value=st.session_state.selected_course_info.get('Nombre de la clase', ''),
            disabled=is_disabled_for_empty_select
        )
        programa = st.text_input(
            "Programa",
            value=st.session_state.selected_course_info.get('Programa', ''),
            disabled=readonly_from_excel
        )
        descripcion = st.text_input(
            "Descripción",
            value=st.session_state.selected_course_info.get('Descripción', 'N/A')
        )
    with col2:
        catalogo = st.text_input(
            "# de Catalogo",
            value=st.session_state.selected_course_info.get('# de Catalogo', ''),
            disabled=readonly_from_excel
        )
        semestre = st.number_input(
            "Semestre", min_value=1, step=1, format="%d",
            value=int(st.session_state.selected_course_info.get('Semestre', 1)),
            disabled=readonly_from_excel
        )
        creditos = st.number_input(
            "Creditos", min_value=1, step=1, format="%d",
            value=int(st.session_state.selected_course_info.get('Creditos', 1)),
            disabled=readonly_from_excel
        )
        simultaneo = st.checkbox(
            "¿Permite Simultaneidad?",
            value=st.session_state.selected_course_info.get('Simultaneo', False)
        )

# --- Centro de costo (selector basado en Excel, sin crear nuevos) ---
with st.container(border=True):
    st.subheader("Centro de Costo y Requerimientos")
    cc_opts = []
    if 'Centro_costo_programa' in curriculum_df.columns:
        try:
            cc_opts = sorted({int(x) for x in curriculum_df['Centro_costo_programa'].dropna().tolist()})
        except Exception:
            # si hay strings, forzamos numéricos válidos
            cc_opts = sorted({int(float(str(x))) for x in curriculum_df['Centro_costo_programa'].dropna().tolist() if str(x).strip() != ''})
    cc_default = st.session_state.selected_course_info.get('Centro_costo_programa', None)
    if cc_default is None and cc_opts:
        cc_default = cc_opts[0]
    centro_costo_programa = st.selectbox(
        "Centro_costo_programa",
        options=cc_opts if cc_opts else [0],
        index=(cc_opts.index(cc_default) if cc_opts and cc_default in cc_opts else 0),
        help="Solo valores existentes en el Excel."
    )

with st.container(border=True):
    st.subheader("Paso 2: Configuración de Sesiones y Requerimientos")
    tipo_clase = st.radio("Tipo de Clase", ["Regular", "Modular"], horizontal=True, key="tipo_clase", disabled=is_disabled_for_empty_select)
    
    req_col1, req_col2 = st.columns(2)
    num_estudiantes = req_col1.number_input("Número de estudiantes estimado", min_value=1, step=1, format="%d", value=25, disabled=is_disabled_for_empty_select)
    req_espacio = req_col2.text_area("Requerimientos específicos del espacio (opcional)", placeholder="Ej: Video beam, tablero, computadores para 30 personas...", disabled=is_disabled_for_empty_select)

    if tipo_clase == "Regular":
        default_ses = st.session_state.get('num_sesiones_a_generar', 1)
        num_sesiones_a_generar = st.number_input("Número de Sesiones a generar", min_value=1, step=1, format="%d",
                                                 key="num_sesiones_a_generar_input", value=default_ses, disabled=is_disabled_for_empty_select)
        if st.button("Generar Campos de Sesión"):
            st.session_state.num_sesiones_a_generar = num_sesiones_a_generar
            st.rerun()
    else:  # Modular
        num_modulos = st.number_input("Número de Módulos", min_value=1, step=1, format="%d", key="num_modulos_input", disabled=is_disabled_for_empty_select)
        if st.button("Generar Módulos"):
            st.session_state.modulos_a_generar = [{'num_sesiones': 1} for _ in range(num_modulos)]
            st.rerun()

# --- Formulario de Sesiones ---
with st.form("new_class_form"):
    st.subheader("Paso 3: Detalles de Fechas, Horarios y Profesores")
    sesiones_data = []

    # Lista de profesores desde S3
    opciones_profesor = ["--- Seleccione un profesor ---"]
    prof_contrato_map = {}
    if not professors_df.empty:
        cols_ok = all(c in professors_df.columns for c in ['Profesor', 'Contrato'])
        if not cols_ok:
            st.warning("El archivo 'profesores.csv' debe contener columnas 'Profesor' y 'Contrato'.")
        else:
            unique_professors = professors_df.dropna(subset=['Profesor']).drop_duplicates(subset=['Profesor'])
            opciones_profesor += sorted(unique_professors['Profesor'].astype(str).tolist())
            prof_contrato_map = pd.Series(unique_professors['Contrato'].astype(str).values, index=unique_professors['Profesor'].astype(str)).to_dict()

    if st.session_state.tipo_clase == "Regular":
        # Prefill profesor y contrato si viene del Excel
        prefill_prof = st.session_state.prefill_profesor
        prefill_contrato_excel = st.session_state.selected_course_info.get('Contrato_prefill', "")
        default_prof_index = opciones_profesor.index(prefill_prof) if prefill_prof and prefill_prof in opciones_profesor else 0

        st.markdown("##### Profesor (asignado a todas las sesiones)")
        profesor_existente_reg = st.selectbox("Profesor Existente", options=opciones_profesor, index=default_prof_index, help="Selecciona un profesor de la lista.")
        profesor_regular = profesor_existente_reg if profesor_existente_reg != "--- Seleccione un profesor ---" else ""

        # Determinar contrato por defecto: Excel > mapa por profesor
        contrato_por_defecto = prefill_contrato_excel.strip() if prefill_contrato_excel else prof_contrato_map.get(profesor_regular, "No especificado")
        if contratos_opciones and contrato_por_defecto not in contratos_opciones:
            contrato_por_defecto = contratos_opciones[0]
        default_contrato_idx = (contratos_opciones.index(contrato_por_defecto) if contratos_opciones and contrato_por_defecto in contratos_opciones else 0)

        contrato_seleccionado = st.selectbox(
            "Contrato (solo categorías existentes)",
            options=contratos_opciones if contratos_opciones else ["No especificado"],
            index=default_contrato_idx if contratos_opciones else 0,
            help="Edita el contrato, pero solo entre las categorías existentes."
        )

        st.markdown("---")
        time_opts = get_time_options()
        def _time_index_or_default(t):
            if isinstance(t, time) and t in time_opts:
                return time_opts.index(t)
            if isinstance(t, time):
                minutes = t.hour * 60 + t.minute
                closest = min(range(len(time_opts)), key=lambda i: abs((time_opts[i].hour*60 + time_opts[i].minute) - minutes))
                return closest
            return 2  # 8:00

        prefill_ses = st.session_state.prefill_sesiones or []
        n = st.session_state.get('num_sesiones_a_generar', 1)

        for i in range(n):
            st.markdown(f"**Sesión {i + 1}**")
            s_col1, s_col2, s_col3 = st.columns(3)

            # Valores por defecto desde prefill (acotados al semestre)
            if i < len(prefill_ses):
                p = prefill_ses[i]
                def_fecha = p.get("Fecha", min_date)
                def_fecha = min(max(def_fecha, min_date), max_date)
                def_inicio = p.get("Hora de inicio", time(8, 0))
                def_dur = p.get("Duracion", 2)
            else:
                def_fecha = min_date
                def_inicio = time(8, 0)
                def_dur = 2

            fecha = s_col1.date_input("Fecha", value=def_fecha, min_value=min_date, max_value=max_date, key=f"reg_date_{i}")
            hora_inicio = s_col2.selectbox("Inicio", options=time_opts, index=_time_index_or_default(def_inicio),
                                           format_func=lambda t: t.strftime('%H:%M'), key=f"reg_start_{i}")
            duracion = s_col3.number_input("Duración (horas enteras)", min_value=1, step=1, value=int(def_dur), key=f"reg_dur_{i}")

            hora_fin_dt = (datetime.combine(date.today(), hora_inicio) + pd.Timedelta(hours=int(duracion)))
            hora_fin = hora_fin_dt.time()
            if hora_fin > time(19, 0):
                st.warning("La duración hace que la clase termine después de las 7:00 PM.")

            sesiones_data.append({
                "Profesor": profesor_regular,
                "Tipo de Contrato": contrato_seleccionado,
                "Módulo": 1,
                "Sesión": i + 1,
                "Fecha": fecha,
                "Hora de inicio": hora_inicio,
                "Hora de finalizacion": hora_fin
            })

    else:  # Modular
        sesion_counter = 1
        for i, mod in enumerate(st.session_state.get('modulos_a_generar', [])):
            st.markdown(f"--- \n ### Módulo {i + 1}")
            profesor_existente_mod = st.selectbox(f"Profesor Existente (M{i+1})", options=opciones_profesor, key=f"prof_existente_mod_{i}", help="Selecciona un profesor para este módulo.")
            profesor_modulo = profesor_existente_mod if profesor_existente_mod != "--- Seleccione un profesor ---" else ""

            contrato_por_defecto_mod = st.session_state.selected_course_info.get('Contrato_prefill', "") or prof_contrato_map.get(profesor_modulo, "No especificado")
            if contratos_opciones and contrato_por_defecto_mod not in contratos_opciones:
                contrato_por_defecto_mod = contratos_opciones[0]
            default_contrato_mod_idx = (contratos_opciones.index(contrato_por_defecto_mod) if contratos_opciones else 0)

            contrato_mod_seleccionado = st.selectbox(
                f"Contrato (M{i+1})",
                options=contratos_opciones if contratos_opciones else ["No especificado"],
                index=default_contrato_mod_idx if contratos_opciones else 0,
                help="Solo categorías existentes para el contrato."
            )

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

                sesiones_data.append({
                    "Profesor": profesor_modulo,
                    "Tipo de Contrato": contrato_mod_seleccionado,
                    "Módulo": i + 1,
                    "Sesión": sesion_counter,
                    "Fecha": fecha,
                    "Hora de inicio": hora_inicio,
                    "Hora de finalizacion": hora_fin
                })
                sesion_counter += 1

    submit_button = st.form_submit_button("Añadir Clase al Cronograma", disabled=is_disabled_for_empty_select)

# --- Envío del formulario ---
if submit_button:
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
            for c in self_conflicts:
                st.warning(c)
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
                'Centro_costo_programa': int(centro_costo_programa),
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
                for c in db_conflicts:
                    st.warning(c)
            else:
                # Convertir a string para la inserción en Supabase
                final_df['Fecha'] = final_df['Fecha'].astype(str)
                final_df['Hora de inicio'] = final_df['Hora de inicio'].astype(str)
                final_df['Hora de finalizacion'] = final_df['Hora de finalizacion'].astype(str)
                
                try:
                    supabase.table('cronograma').insert(final_df.to_dict('records')).execute()
                    st.success(f"¡Clase '{nombre_clase}' añadida exitosamente!")
                    st.cache_data.clear()  # Limpiar caché para recargar los datos
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
    if st.session_state.programa_filtro:
        filtered_df = filtered_df[filtered_df['Programa'].isin(st.session_state.programa_filtro)]
    if st.session_state.profesor_filtro:
        filtered_df = filtered_df[filtered_df['Profesor'].isin(st.session_state.profesor_filtro)]
    if st.session_state.semestre_filtro:
        filtered_df = filtered_df[filtered_df['Semestre'].isin(st.session_state.semestre_filtro)]
    
    st.dataframe(format_for_display(filtered_df.sort_values(by="Fecha")), use_container_width=True)
    
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
        df_for_plot = filtered_df.copy()
        df_for_plot['start'] = df_for_plot.apply(lambda row: pd.to_datetime(f"{row['Fecha']} {row['Hora de inicio']}"), axis=1)
        df_for_plot['end'] = df_for_plot.apply(lambda row: pd.to_datetime(f"{row['Fecha']} {row['Hora de finalizacion']}"), axis=1)

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
        st.plotly_chart(fig_timeline, use_container_width=True)
        
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
        st.plotly_chart(fig_gantt, use_container_width=True)
    else:
        st.warning("No hay datos para mostrar en las visualizaciones con los filtros actuales.")

    # --- Sección de Eliminación ---
    st.markdown("---")
    st.header("🗑️ Eliminar Clase del Cronograma")
    with st.form("delete_form"):
        unique_classes = st.session_state.schedule_df[['Nombre de la clase', '# de Catalogo', 'Programa']].drop_duplicates()
        class_options_delete = [f"{row['Nombre de la clase']} ({row['# de Catalogo']} - {row['Programa']})" for _, row in unique_classes.iterrows()]
        
        class_to_delete_display = st.selectbox("Selecciona la clase a eliminar", options=sorted(class_options_delete))
        
        if st.form_submit_button("Eliminar Clase"):
            if class_to_delete_display:
                catalogo_to_delete = class_to_delete_display.split('(')[1].split(' - ')[0]
                try:
                    supabase.table('cronograma').delete().like('ID', f'{catalogo_to_delete}%').execute()
                    st.success(f"La clase con catálogo '{catalogo_to_delete}' ha sido eliminada.")
                    st.cache_data.clear()
                    st.session_state.schedule_df = load_schedule_data()
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al eliminar de la base de datos: {e}")
