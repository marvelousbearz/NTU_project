import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

df=pd.read_csv('Customer-Churn-Records.csv')

# 数据预处理
df=df.drop(['RowNumber','Surname','CustomerId','Complain'],axis=1)
df['Gender']=df['Gender'].map({'Male':1,'Female':0})
df=pd.get_dummies(df,columns=['Geography','Card Type'],drop_first=True)

# 数据切分
from sklearn.model_selection import train_test_split
X=df.drop(['Exited'],axis=1)
y=df['Exited']
X_train,X_test,y_train,y_test=train_test_split(X,y,test_size=0.2,random_state=42,stratify=y)
X_pseudo_train,X_pseudo_test,y_pseudo_train,y_pseudo_test=train_test_split(X_train,y_train,test_size=0.2,random_state=42,stratify=y_train)

# 数据填充
from imblearn.over_sampling import SMOTE
sm=SMOTE(random_state=42)
X_pseudo_train_resampled,y_pseudo_train_resampled=sm.fit_resample(X_pseudo_train,y_pseudo_train)

# 模型训练
from sklearn.ensemble import RandomForestClassifier
RF=RandomForestClassifier(n_estimators=100,random_state=42)
RF.fit(X_pseudo_train_resampled,y_pseudo_train_resampled)
y_pred=RF.predict(X_pseudo_test)
from sklearn.metrics import accuracy_score,classification_report,confusion_matrix
accuracy=accuracy_score(y_pred,y_pseudo_test)
print(f"the average accuracy rate of RandomForest is:\n{accuracy:.4f}")
print(f"the classification report of RandomForest is:\n{classification_report(y_pred,y_pseudo_test)}")
cm_RF=confusion_matrix(y_pred,y_pseudo_test)
plt.figure(figsize=(6,5))
sns.heatmap(cm_RF,annot=True,fmt='d',cmap='Blues')
plt.title('the heatmap of RandomForest')
plt.xlabel('the true value of data')
plt.ylabel('the predicted value of data')
plt.show()

from sklearn.model_selection import cross_val_score
RF_CV=RandomForestClassifier(n_estimators=100,random_state=42)
Accuracy_score=cross_val_score(RF_CV,X_pseudo_train_resampled,y_pseudo_train_resampled,cv=5,scoring='accuracy')
print(f"the accuracy_score of Random_Forest is:\n{Accuracy_score}")
print(f"the average of accuracy score is:\n{Accuracy_score.mean():.4f}")
Recall=cross_val_score(RF_CV,X_pseudo_train_resampled,y_pseudo_train_resampled,cv=5,scoring='recall')
print(f"the recall of Random_Forest is:\n{Recall}")
print(f"the average of recall is:\n{Recall.mean():.4f}")

import joblib
joblib.dump(RF,'RandomF.pkl')