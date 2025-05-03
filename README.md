## CS527 Term Project-Group 16
---
## Team Member:
Krish, Seunggyu, Anirudh
---
## Teck Stacks
<p align="center">
  <figure style="display:inline-block; text-align:center; margin:0 20px">
    <img src="/images/smtp.png" alt="SMTP" width="120" />
    <figcaption>SMTP Server</figcaption>
  </figure>
  <figure style="display:inline-block; text-align:center; margin:0 20px">
    <img src="/images/html.png" alt="HTML" width="120" />
    <figcaption>HTML5</figcaption>
  </figure>
  <figure style="display:inline-block; text-align:center; margin:0 20px">
    <img src="/images/sqlalchemy.png" alt="SQLAlchemy" width="120" />
    <figcaption>SQLAlchemy ORM</figcaption>
  </figure>
  <figure style="display:inline-block; text-align:center; margin:0 20px">
    <img src="/images/flask.png" alt="Flask" width="120" />
    <figcaption>Flask Framework</figcaption>
  </figure>
</p>

---
## ER-Diagram
![alt text](/images/diagram.png)
---
## Core Features
<p align="center">
  <figure style="display:inline-block; text-align:center; margin:0 20px">
    <img src="/images/user.png" alt="user" width="120" />
  <figcaption>
    User<br/>
    Admin<br/>
    Customer_Representative
  </figcaption>
  </figure>
  <figure style="display:inline-block; text-align:center; margin:0 20px">
    <img src="/images/item.png" alt="item" width="120" />
    <figcaption>Item</figcaption>
  </figure>
  <figure style="display:inline-block; text-align:center; margin:0 20px">
    <img src="/images/auction.png" alt="auction" width="120" />
    <figcaption>Auction</figcaption>
  </figure>
  <figure style="display:inline-block; text-align:center; margin:0 20px">
    <img src="/images/bidding.png" alt="bidding" width="120" />
    <figcaption>Bidding(w/ AutoBidding)</figcaption>
  </figure>
</p>
<p align="center">
  <figure style="display:inline-block; text-align:center; margin:0 20px">
    <img src="/images/qna.png" alt="qna" width="120" />
  <figcaption>Q&A</figcaption>
  </figure>
  <figure style="display:inline-block; text-align:center; margin:0 20px">
    <img src="/images/alert.png" alt="alert" width="120" />
    <figcaption>Alert</figcaption>
  </figure>
  <figure style="display:inline-block; text-align:center; margin:0 20px">
    <img src="/images/browse.png" alt="browse" width="120" />
    <figcaption>Browse</figcaption>
  </figure>
  <figure style="display:inline-block; text-align:center; margin:0 20px">
    <img src="/images/sales_report.png" alt="sales_report" width="120" />
    <figcaption>Sales Report</figcaption>
  </figure>
</p>

---
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