import sys
import os
import sqlite3
from datetime import datetime

db_path = r"c:\Users\diarm\Documents\Liliana Leon\CMR\backend\crm.db"

documents_data = [
    {
        "filename": "Ficha_Tecnica_GLAMPING_DOMO_40m2.pdf",
        "file_type": "PDF",
        "extracted_text": """ANCLA SPECIAL PROJECTS - FICHA TÉCNICA GLAMPING DOMO GEODÉSICO 40m²
- Estructura: Tubo de acero galvanizado con recubrimiento anticorrosivo de alta resistencia.
- Cubierta: Lona PVC termo-sellada importada de 850g/m², protección UV50+, retardante al fuego y 100% impermeable.
- Aislamiento Térmico y Acústico: Aislamiento multicapa de fibra termo-reflectiva de aluminio para climas fríos y cálidos.
- Ventanaje y Decks: Ventanales panorámicos en PVC transparente de alta densidad. Estructura de deck en madera teca / wpc compuesta.
- Usos Recomendados: Proyectos turísticos ecologicos, hoteles boutique, refugios de montaña y zonas cálidas.
- Garantía: 5 años en estructura metálica y 3 años en cubierta exterior."""
    },
    {
        "filename": "Ficha_Tecnica_FLEX_HOME_36m2.pdf",
        "file_type": "PDF",
        "extracted_text": """ANCLA SPECIAL PROJECTS - FICHA TÉCNICA FLEX HOME MODULAR 36m²
- Concepto: Casa modular transportable de rápido ensamblaje (ensamblada en 48 horas).
- Estructura Principal: Perfiles de acero estructural de alta especificación ASTM A36.
- Muros Exteriores e Interiores: Panel sándwich de poliuretano inyectado (PUR/PIR) de 50mm con excelente aislamiento térmico.
- Distribución: 1 Habitación principal, 1 baño completo con acabados modernos, cocina integral tipo americano, sala comedor.
- Acabados de Piso: Piso vinílico SPC tráfico pesado de alta durabilidad resistente al agua.
- Redes: Red eléctrica embutida con certificación RETIE, red hidrosanitaria completa lista para conectar a pozo séptico o red municipal."""
    },
    {
        "filename": "Ficha_Tecnica_FLEX_HOME_56m2.pdf",
        "file_type": "PDF",
        "extracted_text": """ANCLA SPECIAL PROJECTS - FICHA TÉCNICA FLEX HOME MODULAR 56m²
- Distribución: 2 Habitaciones amplias, 1 o 2 baños completos, área social abierta con cocina integral, zona de ropas.
- Estructura: Estructura de acero sismo-resistente galvanizado.
- Aislamiento: Panel sándwich insonorizado y térmico de 75mm en cubierta y muros exteriores.
- Cubierta: Teja termoacústica de PVC arquitectónico con inclinación para evacuación de aguas pluviales.
- Ventanería: Perfilería de aluminio anodizado color negro mate con cristal templado de 6mm.
- Ventajas: Cero desperdicio de materiales, construcción limpia y entrega inmediata."""
    },
    {
        "filename": "Ficha_Tecnica_FLEX_HOME_72m2.pdf",
        "file_type": "PDF",
        "extracted_text": """ANCLA SPECIAL PROJECTS - FICHA TÉCNICA FLEX HOME MODULAR 72m²
- Distribución: 3 Habitaciones, 2 baños completos, amplia sala-comedor, cocina con barra americana y zona de lavandería independiente.
- Estructura: Chasis reforzado en vigas IPE/HEB de acero estructural.
- Eficiencia Energética: Aislamiento térmico térmico de poliuretano de alta densidad de 100mm.
- Acabados Premium: Iluminación LED empotrada, aparatos sanitarios ecológicos de bajo consumo, mesones en cuarzo sintético.
- Opciones Adicionales: Sistema de energía solar fotovoltaica off-grid y sistema de recolección de aguas lluvias."""
    },
    {
        "filename": "Ficha_Tecnica_CAPSULA_LINVIG.pdf",
        "file_type": "PDF",
        "extracted_text": """ANCLA SPECIAL PROJECTS - FICHA TÉCNICA CÁPSULA LINVIG FUTURISTA
- Concepto: Módulo habitacional autónomo de diseño futurista espacial para experiencias de hospedaje de lujo.
- Estructura Exterior: Cascarón monocasco de fibra de vidrio reforzada con resina epóxica y aislamiento térmico de poliuretano inyectado.
- Equipamiento Tecnológico: Cerradura inteligente con clave y tarjeta RFID, control de iluminación ambiental por domótica, sistema de climatización inverter frío/calor.
- Baño Inteligente: Sanitario inteligente con funciones automáticas, ducha con cristal templado de seguridad y grifería monocontrol.
- Ventanal de Observación: Techo panorámico de vidrio templado de 10mm con película UV y privacidad controlada."""
    },
    {
        "filename": "Ficha_Tecnica_CUARTOS_FRIOS_REFRIGERACION.pdf",
        "file_type": "PDF",
        "extracted_text": """ANCLA SPECIAL PROJECTS - FICHA TÉCNICA CUARTOS FRÍOS DE REFRIGERACIÓN (0°C A 5°C)
- Aplicación: Conservación de frutas, verduras, lácteos, carnes frescas, flores y productos farmacéuticos.
- Paneles Modulares: Paneles sándwich de poliuretano inyectado (PUR) de 100mm con densidad de 40 kg/m³, encable macho-hembra hermético.
- Recubrimiento: Lámina de acero galvanizado prepintado blanco sanitario o acero inoxidable 304 de grado alimenticio.
- Unidad Condensadora y Evaporador: Equipos de alta eficiencia energética con refrigerantes ecológicos R404A / R448A, motores electrónicos de bajo consumo.
- Puertas: Puertas correderas o batientes con sello magnético, marco calefaccionado para evitar condensación y cortina de láminas de PVC transparentes."""
    },
    {
        "filename": "Ficha_Tecnica_CUARTOS_FRIOS_CONGELACION.pdf",
        "file_type": "PDF",
        "extracted_text": """ANCLA SPECIAL PROJECTS - FICHA TÉCNICA CUARTOS FRÍOS DE CONGELACIÓN (-18°C A -25°C)
- Aplicación: Congelación y almacenamiento de carnes, pescados, mariscos, pulpa de fruta, helados y productos ultracongelados.
- Espesor de Panel: Panel sándwich de poliuretano (PIR/PUR) de 150mm de espesor con alto coeficiente de aislamiento K=0.022 W/mK.
- Piso Aislado: Piso reforzado con aislamiento térmico rígido, lámina de aluminio antideslizante o piso de concreto pulido para montacargas.
- Sistema de Control: Tablero eléctrico con controlador digital microprocesado, alarmas de temperatura, registro de datos y monitoreo remoto por WiFi/IoT.
- Seguridad: Válvula de despresurización para evitar vacío por cambio de temperatura y hacha de emergencia interior."""
    },
    {
        "filename": "Ficha_Tecnica_BODEGAS_INDUSTRIALES_MODULARES.pdf",
        "file_type": "PDF",
        "extracted_text": """ANCLA SPECIAL PROJECTS - FICHA TÉCNICA BODEGAS INDUSTRIALES Y COMERCIALES
- Estructura: Naves industriales de estructura metálica empernada en perfiles de acero IPE / WF de alta resistencia estructural.
- Luces Libres: Diseños sin columnas intermedias con luces libres de 12m hasta 40 metros de ancho.
- Cubiertas y Fachadas: Cubierta en teja standing seam termoacústica o panel sándwich de lana de roca / poliuretano.
- Cimentación y Pisos: Diseño adaptado a estudios de suelos, losas de concreto de alta resistencia tratadas con endurecedor superficial de cuarzo.
- Tiempo de Ejecución: Fabricación e instalación en tiempo récord (un 60% más rápido que la construcción tradicional en mampostería)."""
    },
    {
        "filename": "Ficha_Tecnica_ESTRUCTURAS_METALICAS_ESPECIALES.pdf",
        "file_type": "PDF",
        "extracted_text": """ANCLA SPECIAL PROJECTS - FICHA TÉCNICA ESTRUCTURAS METÁLICAS ESPECIALES
- Alcance: Puentes peatonales, cubiertas para polideportivos, mezanines industriales, estructuras para edificios y proyectos a medida.
- Procesos de Soldadura: Soldadores homologados bajo norma AWS D1.1, soldadura MIG/MAG y arco sumergido.
- Protección Anticorrosiva: Granallado comercial SSPC-SP6 y pintura epóxica de altos sólidos con acabado en poliuretano para zonas marinas y altamente corrosivas.
- Control de Calidad: Inspección con ensayos no destructivos (Tintas penetrantes, Ultrasonido estructural y Partículas magnéticas)."""
    },
    {
        "filename": "Dossier_Modular_Ancla_Asia.txt",
        "file_type": "TXT",
        "extracted_text": """ANCLA SPECIAL PROJECTS - DOSSIER DE ALIANZAS INTERNACIONALES Y FABRICACIÓN ASIA
- Garantía de Calidad: Componentes metálicos, paneles y tecnología domótica fabricados bajo estándares internacionales ISO 9001 y CE.
- Capacidad de Producción: Más de 500 módulos al mes listos para exportación y montaje en Colombia y América Latina.
- Logística e Importación: Cadena logística directa sin intermediarios, importación legal con aranceles al día y transporte nacional garantizado."""
    },
    {
        "filename": "Manual_Garantia_y_Servicio_Postventa_Ancla.pdf",
        "file_type": "PDF",
        "extracted_text": """ANCLA SPECIAL PROJECTS - MANUAL DE GARANTÍA Y SERVICIO POSTVENTA
- Cobertura de Garantía: 5 años en estructura metálica principal, 3 años en paneles termoacústicos y 1 año en componentes eléctricos e hidrosanitarios.
- Soporte Técnico: Atención técnica prioritaria de mantenimiento preventivo y correctivo en todo el territorio nacional.
- Compromiso de Calidad: ANCLA Special Projects garantiza cero defectos de fabricación y soporte continuo en cada uno de sus proyectos."""
    }
]

def seed_documents():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename VARCHAR(255) NOT NULL,
            file_type VARCHAR(50) NOT NULL,
            extracted_text TEXT NOT NULL,
            created_at DATETIME NOT NULL
        );
    """)
    
    # Limpiar tabla anterior si existía para dejar los 11 exactos
    cursor.execute("DELETE FROM knowledge_documents;")
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for doc in documents_data:
        cursor.execute(
            "INSERT INTO knowledge_documents (filename, file_type, extracted_text, created_at) VALUES (?, ?, ?, ?);",
            (doc["filename"], doc["file_type"], doc["extracted_text"], now_str)
        )
    
    conn.commit()
    cursor.execute("SELECT count(*) FROM knowledge_documents;")
    count = cursor.fetchone()[0]
    print(f"Total de documentos en knowledge_documents: {count}")
    conn.close()

if __name__ == "__main__":
    seed_documents()
