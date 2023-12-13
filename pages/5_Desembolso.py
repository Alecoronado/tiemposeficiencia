import streamlit as st
import pandas as pd
from streamlit.logger import get_logger
import altair as alt
import re
from datetime import datetime
import threading
import io

LOGGER = get_logger(__name__)
_lock = threading.Lock()

# URLs de las hojas de Google Sheets
sheet_url_proyectos = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSHedheaRLyqnjwtsRvlBFFOnzhfarkFMoJ04chQbKZCBRZXh_2REE3cmsRC69GwsUK0PoOVv95xptX/pub?gid=2084477941&single=true&output=csv"
sheet_url_operaciones = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSHedheaRLyqnjwtsRvlBFFOnzhfarkFMoJ04chQbKZCBRZXh_2REE3cmsRC69GwsUK0PoOVv95xptX/pub?gid=1468153763&single=true&output=csv"
sheet_url_desembolsos = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSHedheaRLyqnjwtsRvlBFFOnzhfarkFMoJ04chQbKZCBRZXh_2REE3cmsRC69GwsUK0PoOVv95xptX/pub?gid=1657640798&single=true&output=csv"

def convert_monto_to_numeric(monto_str):
    if pd.isnull(monto_str):
        return None
    try:
        return float(monto_str.replace('.', '').replace(',', '.'))
    except ValueError:
        LOGGER.error(f"Error al convertir el monto: {monto_str}")
        return None

# Función para convertir las fechas del formato español al formato estándar
def convert_spanish_date(date_str):
    months = {
        'ENE': 'Jan', 'FEB': 'Feb', 'MAR': 'Mar', 'ABR': 'Apr', 'MAY': 'May', 'JUN': 'Jun',
        'JUL': 'Jul', 'AGO': 'Aug', 'SEP': 'Sep', 'OCT': 'Oct', 'NOV': 'Nov', 'DIC': 'Dec'
    }
    match = re.match(r"(\d{2}) (\w{3}) (\d{2})", date_str)
    if match:
        day, spanish_month, year = match.groups()
        english_month = months.get(spanish_month.upper())
        if english_month:
            return datetime.strptime(f"{day} {english_month} 20{year}", "%d %b %Y").strftime("%d/%m/%Y")
    return date_str

# Función para manejar diferentes formatos de fechas y valores nulos
def convert_dates(date_str):
    if pd.isnull(date_str):
        return None

    if not isinstance(date_str, str):
        return date_str

    months = {
        'ene': '01', 'feb': '02', 'mar': '03', 'abr': '04', 'may': '05', 'jun': '06',
        'jul': '07', 'ago': '08', 'sep': '09', 'oct': '10', 'nov': '11', 'dic': '12'
    }

    try:
        # Formato '15-ago-14' o '1-dic-17'
        day, month, year = date_str.split('-')
        if len(year) == 2: year = f"20{year}"
        month = months.get(month[:3].lower(), '00')
        return f"{day.zfill(2)}/{month}/{year}"
    except ValueError:
        pass

    try:
        # Formato 'martes, 17 de noviembre de 2015'
        parts = date_str.split(' ')
        day = parts[1]
        month = parts[3].lower()[:3]
        year = parts[5]
        return f"{day.zfill(2)}/{months[month]}/{year}"
    except (ValueError, IndexError):
        pass

    try:
        # Formato '13-abr-20'
        return datetime.strptime(date_str, '%d-%b-%y').strftime('%d/%m/%Y')
    except ValueError:
        pass

    return date_str

# Función para cargar los datos desde la URL
def load_data_from_url(url):
    with _lock:
        try:
            return pd.read_csv(url)
        except Exception as e:
            LOGGER.error("Error al cargar los datos: " + str(e))
            return None

# Adaptación de la función process_dataframe para cargar desde Google Sheets
def process_data():
    proyectos = load_data_from_url(sheet_url_proyectos)
    operaciones = load_data_from_url(sheet_url_operaciones)
    operaciones_desembolsos = load_data_from_url(sheet_url_desembolsos)

    # Verificar la carga correcta de datos
    if proyectos is None or operaciones is None or operaciones_desembolsos is None:
        st.error("Error en la carga de datos desde Google Sheets.")
        return pd.DataFrame()

    # Aplicar la conversión de fechas
    for df in [proyectos, operaciones, operaciones_desembolsos]:
        if 'FechaEfectiva' in df.columns:
            df['FechaEfectiva'] = df['FechaEfectiva'].apply(convert_dates)
        if 'FechaVigencia' in df.columns:
            df['FechaVigencia'] = df['FechaVigencia'].apply(convert_dates)

    # Limpiar y convertir la columna 'Monto' en operaciones_desembolsos
    operaciones_desembolsos['Monto'] = operaciones_desembolsos['Monto'].apply(convert_monto_to_numeric)
    operaciones['AporteFONPLATAVigente'] = operaciones['AporteFONPLATAVigente'].apply(convert_monto_to_numeric)

    # Fusionar los datos
    merged_op_desembolsos = pd.merge(operaciones, operaciones_desembolsos, on=['NoOperacion', 'NoEtapa'], how='left')
    merged_all = pd.merge(merged_op_desembolsos, proyectos, on='NoProyecto', how='left')

    # Convertir fechas a datetime y calcular la diferencia en años
    merged_all['Monto'] = pd.to_numeric(merged_all['Monto'], errors='coerce')
    merged_all['AporteFONPLATAVigente'] = pd.to_numeric(merged_all['AporteFONPLATAVigente'], errors='coerce')
    merged_all['FechaEfectiva'] = pd.to_datetime(merged_all['FechaEfectiva'], dayfirst=True)
    merged_all['FechaVigencia'] = pd.to_datetime(merged_all['FechaVigencia'], dayfirst=True)
    merged_all.dropna(subset=['FechaEfectiva', 'FechaVigencia'], inplace=True)
    merged_all['Ano'] = ((merged_all['FechaEfectiva'] - merged_all['FechaVigencia']).dt.days / 366).astype(int)

    # Realizar cálculos utilizando 'AporteFONPLATA'
    result_df = merged_all.groupby(['NoProyecto', 'Ano', 'IDEtapa'])['Monto'].sum().reset_index()
    result_df['Monto Acumulado'] = result_df.groupby(['NoProyecto'])['Monto'].cumsum().reset_index(drop=True)


    # Verificar si 'AporteFONPLATA' está en 'operaciones'
    if 'AporteFONPLATAVigente' in operaciones.columns:
        result_df = pd.merge(result_df, operaciones[['NoProyecto', 'AporteFONPLATAVigente']], on='NoProyecto', how='left')
        result_df['Porcentaje del Monto'] = result_df['Monto'] / result_df['AporteFONPLATAVigente'] * 100
        result_df['Porcentaje del Monto Acumulado'] = result_df['Monto Acumulado'] / result_df['AporteFONPLATAVigente'] * 100
    else:
        st.error("La columna 'AporteFONPLATA' no se encontró en la hoja 'Operaciones'.")

    # Añadir 'IDAreaPrioritaria' (Sector) y 'IDAreaIntervencion' (Subsector) al DataFrame resultante
    result_df = pd.merge(result_df, proyectos[['NoProyecto', 'IDAreaPrioritaria', 'IDAreaIntervencion','Alias']], on='NoProyecto', how='left')

    return result_df


# Función para convertir DataFrame a bytes para descargar en Excel
def dataframe_to_excel_bytes(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Resultados', index=False)
    output.seek(0)
    return output

def run():
    st.set_page_config(
        page_title="Desembolsos",
        page_icon="👋",
    )

    st.title("Desembolsos de Proyectos📊")
    st.write("Explora las métricas relacionadas con los desembolsos cargando los datos desde Google Sheets.")

    # Procesar datos desde Google Sheets
    result_df = process_data()
    if not result_df.empty:
        st.write(result_df)
        
        # Convertir el DataFrame a bytes y agregar botón de descarga
        excel_bytes = dataframe_to_excel_bytes(result_df)
        st.download_button(
            label="Descargar DataFrame en Excel",
            data=excel_bytes,
            file_name="resultados_desembolsos.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

        # Definir colores para los gráficos
        color_monto = 'steelblue'
        color_porcentaje = 'firebrick'
        color_acumulado = 'goldenrod'
        
        # Asegurar que las columnas necesarias estén presentes
        if 'IDEtapa' in result_df.columns:
            # Crear una serie combinada con 'IDEtapa' y 'APODO' si está disponible
            if 'Alias' in result_df.columns:
                combined_series = result_df['IDEtapa'] + " (" + result_df['Alias'] + ")"
            else:
                combined_series = result_df['IDEtapa'].astype(str)
            
            # Ordenar las opciones alfabéticamente
            sorted_combined_series = combined_series.sort_values()

            # Usar la serie ordenada en el selectbox
            selected_combined = st.selectbox('Selecciona el Proyecto:', sorted_combined_series.unique())
            selected_etapa = selected_combined.split(" (")[0]
            filtered_df = result_df[result_df['IDEtapa'] == selected_etapa]

            if 'AporteFONPLATAVigente' in filtered_df.columns:
                # Perform calculations only if 'AporteFONPLATA' is available
                df_monto_anual = filtered_df.groupby('Ano')['Monto'].sum().reset_index()
                df_monto_acumulado_anual = df_monto_anual['Monto'].cumsum()

                aporte_total = filtered_df['AporteFONPLATAVigente'].iloc[0]
                df_porcentaje_monto_anual = (df_monto_anual['Monto'] / aporte_total * 100).round(2)
                df_porcentaje_monto_acumulado_anual = (df_monto_acumulado_anual / aporte_total * 100).round(2)

                combined_df = pd.DataFrame({
                    'Ano': df_monto_anual['Ano'],
                    'Monto': df_monto_anual['Monto'],
                    'Monto Acumulado': df_monto_acumulado_anual,
                    'Porcentaje del Monto': df_porcentaje_monto_anual,
                    'Porcentaje del Monto Acumulado': df_porcentaje_monto_acumulado_anual
                })

                st.write("Resumen de Datos:")
                st.write(combined_df)
                
                # Ensure 'Monto' is in the combined_df before attempting to modify it
                if 'Monto' in combined_df.columns:
                    combined_df['Monto'] = (combined_df['Monto'] / 1_000_000).round(3)
                # Additional code for chart generation goes here...
            else:
                st.error("La columna 'AporteFONPLATA' no está presente en los datos cargados.")
        else:
            st.error("La columna 'IDEtapa' no está presente en los datos cargados.")


        # Función para crear gráficos de líneas con puntos y etiquetas
        def line_chart_with_labels(data, x_col, y_col, title, color):
            # Gráfico de línea con puntos
            chart = alt.Chart(data).mark_line(point=alt.OverlayMarkDef(color=color, fill='black', strokeWidth=2), strokeWidth=3).encode(
                x=alt.X(f'{x_col}:N', axis=alt.Axis(title='Año', labelAngle=0)),
                y=alt.Y(f'{y_col}:Q', axis=alt.Axis(title=y_col)),
                color=alt.value(color),
                tooltip=[x_col, y_col]
            ).properties(
                title=title,
                width=600,
                height=400
            )

            # Etiquetas de texto para cada punto
            text = chart.mark_text(
                align='left',
                baseline='middle',
                dx=20,  # Desplazamiento en el eje X para evitar solapamiento con los puntos
                dy=-20  # Desplazamiento en el eje Y para alejar el texto de la línea
            ).encode(
                text=alt.Text(f'{y_col}:Q'),
                color=alt.value('black')  # Establece el color del texto a negro
            )
            return chart + text  # Combinar gráfico de línea con etiquetas

        # Crear los tres gráficos con etiquetas
        chart_monto = line_chart_with_labels(combined_df, 'Ano', 'Monto', 'Monto por Año en Millones de USD', color_monto)
        chart_porcentaje_monto = line_chart_with_labels(combined_df, 'Ano', 'Porcentaje del Monto', 'Porcentaje del Monto Desembolsado por Año', color_porcentaje)
        chart_porcentaje_monto_acumulado = line_chart_with_labels(combined_df, 'Ano', 'Porcentaje del Monto Acumulado', 'Porcentaje del Monto Acumulado por Año', color_acumulado)

        # Mostrar los gráficos en Streamlit
        st.altair_chart(chart_monto, use_container_width=True)
        st.altair_chart(chart_porcentaje_monto, use_container_width=True)
        st.altair_chart(chart_porcentaje_monto_acumulado, use_container_width=True)

if __name__ == "__main__":
    run()