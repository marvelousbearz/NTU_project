import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns

df=pd.read_csv('Customer-Churn-Records.csv')
df=df.drop(['RowNumber','Surname','CustomerId','Complain'],axis=1)

df['Gender']=df['Gender'].map({'Male':1,'Female':0})
df=pd.get_dummies(df,columns=['Geography','Card Type'],drop_first=True)

from sklearn.model_selection import train_test_split
X=df.drop('Exited',axis=1)
y=df['Exited']
X_train,X_test,y_train,y_test=train_test_split(X,y,test_size=0.2,random_state=42,stratify=y)
X_pseudo_train,X_pseudo_test,y_pseudo_train,y_pseudo_test=train_test_split(X_train,y_train,test_size=0.25,random_state=42,stratify=y_train)
print(f"X训练集的大小是{X_train.shape[0]}")
print(f"X的pseudo训练集的大小是{X_pseudo_train.shape[0]}")

from imblearn.over_sampling import SMOTE
sm=SMOTE(random_state=42)
X_pseudo_train_resampled,y_pseudo_train_resampled=sm.fit_resample(X_pseudo_train,y_pseudo_train)
print(f"平衡前流失/未流失的比例为:{y_pseudo_train.value_counts(normalize=True)}")
print(f"平衡后流失/未流失的比例为:{y_pseudo_train_resampled.value_counts(normalize=True)}")

from sklearn.preprocessing import StandardScaler
scaler=StandardScaler()
X_pseudo_train_scaled=scaler.fit_transform(X_pseudo_train_resampled)
X_pseudo_test_scaled=scaler.transform(X_pseudo_test)


from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score,classification_report,confusion_matrix
model_LR=LogisticRegression(random_state=42,max_iter=1000,solver='saga')
model_LR.fit(X_pseudo_train_scaled,y_pseudo_train_resampled)
y_pred=model_LR.predict(X_pseudo_test_scaled)
accuracy=accuracy_score(y_pred,y_pseudo_test)
print(f"准确率是:{accuracy:.4f}")
print(f"分类报告如下所示:\n{classification_report(y_pred,y_pseudo_test)}")

cm=confusion_matrix(y_pred,y_pseudo_test)
plt.figure(figsize=(6,5))
sns.heatmap(cm,annot=True,fmt='d',cmap='Blues')
plt.title('confusion matrix of Logistic Regression')
plt.xlabel('True label')
plt.ylabel('Predict label')
plt.show()

from sklearn.model_selection import cross_val_score
LR_CV=LogisticRegression(random_state=42,max_iter=1000,solver='saga')
Accuracy_score=cross_val_score(LR_CV,X_pseudo_train_scaled,y_pseudo_train_resampled,cv=5,scoring='accuracy')
print(f"F-fold得到的准确率是:\n{Accuracy_score}")
print(f"F-fold得到的准确率平均值是:\n{Accuracy_score.mean():.4f}")

Recall_score=cross_val_score(LR_CV,X_pseudo_train_scaled,y_pseudo_train_resampled,cv=5,scoring='recall')
print(f"F-fold得到的Recall结果是:\n{Recall_score}")
print(f"F-fold得到的Recall平均值是:\n{Recall_score.mean():.4f}")

