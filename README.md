## CS527 Term Project-Group 16
---
Team Member:
Krish, Seunggyu, Anirudh
---
<img src="/images/smtp.png" alt="SMTP" width="64" height="64" />
<img src="/images/html.png" alt="HTML"  width="64" height="64" />
<img src="/images/sqlalchemy.png" alt="SQLAlchemy" width="64" height="64" />
<img src="/images/flask.png" alt="Flask" width="64" height="64" />
1. Execute the application code.
```
python run.py
```
2. Turn on the local aiosmtpd server 
```
python -m aiosmtpd -n -l localhost:1025
```
3. Add a admin to the database. 
```
curl -X POST http://localhost:5000/admin/register \
     -H "Content-Type: application/json" \
     -d '{
           "username": "admin",
           "password": "1q2w3e4r",
           "email":    "admin@example.com"
         }'
```