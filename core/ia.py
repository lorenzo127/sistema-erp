import os
import joblib
import pandas as pd
from django.conf import settings
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.feature_extraction.text import TfidfTransformer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline
from .models import CajaChica  # <--- CAMBIO IMPORTANTE

MODEL_PATH = os.path.join(settings.BASE_DIR, 'ia_cajachica.pkl')

def entrenar_modelo():
    """
    Entrena la IA usando el historial de Caja Chica.
    Input: descripcion
    Output: tipo_documento (Boleta, Factura, Peaje, etc.)
    """
    # 1. Obtenemos los datos
    datos = CajaChica.objects.all().values('descripcion', 'tipo_documento')
    df = pd.DataFrame(list(datos))

    if len(df) < 5:
        return False, "Necesito al menos 5 registros en Caja Chica para aprender."

    # 2. Preparamos (X = Texto, y = Etiqueta)
    X = df['descripcion']
    y = df['tipo_documento']

    # 3. Pipeline de aprendizaje
    text_clf = Pipeline([
        ('vect', CountVectorizer()),
        ('tfidf', TfidfTransformer()),
        ('clf', MultinomialNB()),
    ])

    # 4. Entrenar
    text_clf.fit(X, y)

    # 5. Guardar
    joblib.dump(text_clf, MODEL_PATH)
    
    return True, f"IA entrenada con {len(df)} gastos de caja chica."

def predecir_categoria(texto_descripcion):
    if not os.path.exists(MODEL_PATH):
        return None

    try:
        modelo = joblib.load(MODEL_PATH)
        prediccion = modelo.predict([texto_descripcion])[0]
        return prediccion
    except:
        return None