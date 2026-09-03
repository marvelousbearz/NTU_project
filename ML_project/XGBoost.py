import warnings
warnings.filterwarnings('ignore')
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

# 数据预处理
df=pd.read_csv('Customer-Churn-Records.csv')
df=df.drop(['RowNumber','Surname','CustomerId','Complain'],axis=1)
df['Gender']=df['Gender'].map({'Male':1,'Female':0})
df=pd.get_dummies(df,columns=['Geography','Card Type'],drop_first=True)

# 数据切分
from sklearn.model_selection import train_test_split
X=df.drop('Exited',axis=1)
y=df['Exited']
X_train,X_test,y_train,y_test=train_test_split(X,y,test_size=0.2,random_state=42,stratify=y)
X_pseudo_train,X_pseudo_test,y_pseudo_train,y_pseudo_test=train_test_split(X_train,y_train,test_size=0.25,random_state=42,stratify=y_train)

# 数据填充
from imblearn.over_sampling import SMOTE
sm=SMOTE(random_state=42)
X_pseudo_train_resampled,y_pseudo_train_resampled=sm.fit_resample(X_pseudo_train,y_pseudo_train)

# 模型训练
from xgboost import XGBClassifier
model_XGB=XGBClassifier(n_estimators=100, learning_rate=0.1, random_state=42, use_label_encoder=False, eval_metric='logloss')
model_XGB.fit(X_pseudo_train_resampled,y_pseudo_train_resampled)
from sklearn.metrics import accuracy_score,confusion_matrix,classification_report
y_pred=model_XGB.predict(X_pseudo_test)
Accuracy_score=accuracy_score(y_pred,y_pseudo_test)
print(f"the accuracy score of XGBoost is:\n{Accuracy_score:.4f}")
print(f"the classification report of XGBoost is:\n{classification_report(y_pred,y_pseudo_test)}")

cm=confusion_matrix(y_pred,y_pseudo_test)
plt.figure(figsize=(6,5))
sns.heatmap(cm,cmap='Blues',annot=True,fmt='d')
plt.title('confusion matrix of XGBoost')
plt.xlabel('true value')
plt.ylabel('predicted value')
plt.show()

from sklearn.model_selection import cross_val_score
model_test=XGBClassifier(n_estimator=100,learning_rate=0.1,random_state=42,use_label_encoder=False, eval_metric='logloss')
Accuracy=cross_val_score(model_test,X_pseudo_train_resampled,y_pseudo_train_resampled,scoring='accuracy',cv=5)
print(f"the accuracy of XGBoost in 5-fold is:\n{Accuracy}")
print(f"the average of accuracy is:\n{Accuracy.mean():.4f}")
Recall=cross_val_score(model_test,X_pseudo_train_resampled,y_pseudo_train_resampled,cv=5,scoring='recall')
print(f"the recall of XGBoost in 5-fold is:\n{Recall}")
print(f"the average of recall is:\n{Recall.mean():.4f}")