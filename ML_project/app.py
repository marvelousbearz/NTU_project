import streamlit as st
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
import joblib

st.set_page_config(page_title="银行客户流失预测系统Bank Customer Churn Prediction System",layout="wide")
st.title("Bank Customer Churn Prediction System 银行客户流失预测系统")
st.markdown("Information Input 请按照要求输入客户信息")
st.divider()

model=joblib.load('RandomF.pkl')

st.header("Information Input 客户信息输入")
with st.expander("click to open/close Information Input",expanded=False):
    col1,col2=st.columns(2)

with col1:
    credit_score=st.number_input("Credit_Score(信用评分)",min_value=300,max_value=850,value=600)
    age=st.number_input("Age(年龄)",min_value=18,max_value=100,value=30)
    tenure=st.number_input("Tenure(在行年限)",min_value=1,max_value=20,value=3)
    balance=st.number_input("Balance(账户余额)",min_value=0.00,value=50000.00)
    num_products=st.number_input("Num of Products(持有产品数目)",min_value=0,value=5)
    satisfaction_score=st.number_input("Satisfaction Score(满意度分数)",min_value=0,max_value=10,value=5)

with col2:
    has_cr_card=st.selectbox("HasCreaditCard?(是否持有信用卡？)",options=[0,1],format_func=lambda x:'yes(是)' if x==1 else 'no(否)')
    is_active=st.selectbox("IsActiveMember(是否是活跃用户？)",options=[0,1],format_func=lambda x:'yes(是)' if x==1 else 'no(否)')
    estimated_salary=st.number_input("Estimated salary(预估年薪)",min_value=0.00,value=100000.00)
    geography=st.selectbox("Geography(国家)",options=['France','Germany','Spain'])
    gender=st.selectbox("Gender(性别)",options=['Male','Female'])
    point_earned = st.number_input("Point Earned(积分)", min_value=0, max_value=1000, value=500)
    card_type=st.selectbox("Card Type(卡类型)",options=['Gold','Platinum','Silver','None'],index=3)


input_data={
    'CreditScore':credit_score,
    'Age':age,
    'Tenure':tenure,
    'Balance':balance,
    'NumOfProducts':num_products,
    'HasCrCard':has_cr_card,
    'IsActiveMember':is_active,
    'EstimatedSalary':estimated_salary,
    'Satisfaction Score':satisfaction_score,
    'Gender':1 if gender=='Male' else 0,
    'Geography_Germany':1 if geography=='Germany' else 0,
    'Geography_Spain':1 if geography=='Spain' else 0,
    'Card Type_GOLD':1 if card_type=='Gold' else 0,
    'Card Type_PLATINUM':1 if card_type=='Platinum' else 0,
    'Card Type_SILVER':1 if card_type=='Silver' else 0,
    'Point Earned':point_earned
}
training_columns=['CreditScore', 'Gender', 'Age', 'Tenure', 'Balance', 'NumOfProducts', 'HasCrCard', 'IsActiveMember', 'EstimatedSalary', 'Satisfaction Score', 'Point Earned', 'Geography_Germany', 'Geography_Spain', 'Card Type_GOLD', 'Card Type_PLATINUM', 'Card Type_SILVER']
input_df = pd.DataFrame([input_data])[training_columns]

if st.button("🔮预测流失风险🔮",type="primary",use_container_width=True):
    # 使用模型进行预测
    prediction_proba = model.predict_proba(input_df)[0][1]
    prediction = model.predict(input_df)[0]
    
    # 显示预测结果
    st.subheader("📊 预测结果")
    
    if prediction == 1:
        st.error(f"🚨 预警：该客户流失风险极高！\n流失概率约为 **{prediction_proba * 100:.2f}%**。建议立即采取挽留措施。")
        st.progress(prediction_proba)
        st.markdown("**风险提示：** 客户可能因产品满意度、服务体验或竞争银行优惠等原因离开。")
    else:
        st.success(f"✅ 该客户流失风险较低。\n流失概率约为 **{prediction_proba * 100:.2f}%**。")
        st.markdown("**建议：** 可正常提供常规服务，无需额外干预。")