import streamlit as st
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
import joblib
from AI_agent import ask_ai

st.markdown("""
<style>
    .stApp {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
    }
    
    .stNumberInput > div > div > input {
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    .stSelectbox > div > div > div {
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    .stButton > button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 10px 20px;
        font-size: 16px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.2);
    }
</style>
""", unsafe_allow_html=True)

st.set_page_config(page_title="Bank Customer Churn Prediction System",layout="wide")
st.title("Bank Customer Churn Prediction System")
st.divider()

model=joblib.load('RandomF.pkl')

st.header("📖 Information Input")
with st.expander("click to open/close Information Input", expanded=False):
    col1, col2 = st.columns(2)

    with col1:
        credit_score = st.number_input("Credit_Score", min_value=300, max_value=850, value=600)
        age = st.number_input("Age", min_value=18, max_value=100, value=30)
        tenure = st.number_input("Tenure", min_value=1, max_value=20, value=3)
        balance = st.number_input("Balance", min_value=0.00, value=50000.00)
        num_products = st.number_input("Num of Products", min_value=0, value=5)
        satisfaction_score = st.number_input("Satisfaction Score", min_value=0, max_value=10, value=5)

    with col2:
        has_cr_card = st.selectbox("HasCreaditCard?", options=[0, 1], format_func=lambda x: 'yes(是)' if x == 1 else 'no(否)')
        is_active = st.selectbox("IsActiveMember", options=[0, 1], format_func=lambda x: 'yes(是)' if x == 1 else 'no(否)')
        estimated_salary = st.number_input("Estimated salary", min_value=0.00, value=100000.00)
        geography = st.selectbox("Geography", options=['France', 'Germany', 'Spain'])
        gender = st.selectbox("Gender", options=['Male', 'Female'])
        point_earned = st.number_input("Point Earned", min_value=0, max_value=1000, value=500)
        card_type = st.selectbox("Card Type", options=['Gold', 'Platinum', 'Silver', 'None'], index=3)


input_data = {
    'CreditScore': credit_score,
    'Age': age,
    'Tenure': tenure,
    'Balance': balance,
    'NumOfProducts': num_products,
    'HasCrCard': has_cr_card,
    'IsActiveMember': is_active,
    'EstimatedSalary': estimated_salary,
    'Satisfaction Score': satisfaction_score,
    'Gender': 1 if gender == 'Male' else 0,
    'Geography_Germany': 1 if geography == 'Germany' else 0,
    'Geography_Spain': 1 if geography == 'Spain' else 0,
    'Card Type_GOLD': 1 if card_type == 'Gold' else 0,
    'Card Type_PLATINUM': 1 if card_type == 'Platinum' else 0,
    'Card Type_SILVER': 1 if card_type == 'Silver' else 0,
    'Point Earned': point_earned
}
training_columns = ['CreditScore', 'Gender', 'Age', 'Tenure', 'Balance', 'NumOfProducts', 'HasCrCard', 'IsActiveMember', 'EstimatedSalary', 'Satisfaction Score', 'Point Earned', 'Geography_Germany', 'Geography_Spain', 'Card Type_GOLD', 'Card Type_PLATINUM', 'Card Type_SILVER']
input_df = pd.DataFrame([input_data])[training_columns]

if st.button("🔮 Predict the risk 🔮", type="primary", use_container_width=True):
    st.session_state.prediction_proba = model.predict_proba(input_df)[0][1]
    st.session_state.prediction = model.predict(input_df)[0]

# 预测结果保存在 session_state 中，这样打字提问触发的 rerun 不会丢失状态
if "prediction" in st.session_state:
    prediction_proba = st.session_state.prediction_proba
    prediction = st.session_state.prediction

    st.subheader("📊 Result")

    if prediction == 1:
        st.error(f"🚨 Warning: This customer has an extremely high risk of leaving!\nThe probability is **{prediction_proba * 100:.2f}%**. \nIt is recommended to take immediate measures to retain the employee.")
        st.progress(prediction_proba)
        st.markdown("Risk Disclosure: Customers may leave due to reasons such as product satisfaction, service experience, or competitive bank offers.")
    else:
        st.success(f"✅ This customer has a relatively low risk of leaving.\nThe probability is **{prediction_proba * 100:.2f}%**。")
        st.markdown("Suggestion: Regular services can be provided normally without any additional intervention.")

    st.markdown("---")
    st.header("🤖 AI Intelligent Analysis Assistant")
    context = f"客户流失概率为 {prediction_proba*100:.2f}%。预测结果：{'流失' if prediction==1 else '不流失'}。"
    user_question = st.chat_input("Ask AI: Why would this customer leave?")

    if user_question:
        with st.spinner("🤖 AI is analysing..."):
            ai_reply = ask_ai(user_question, context)
        st.markdown(f"**🤖 AI reply: **\n\n{ai_reply}")