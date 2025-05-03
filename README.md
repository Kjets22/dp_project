# CS527 Term Project-Group 16
## Team Member
Krish(kj432), Seunggyu(sl2486), Anirudh(lb1115)

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
    <figcaption>SQLAlchemy</figcaption>
  </figure>
  <figure style="display:inline-block; text-align:center; margin:0 20px">
    <img src="/images/flask.png" alt="Flask" width="120" />
    <figcaption>Flask Framework</figcaption>
  </figure>
</p>


## ER-Diagram
![alt text](/images/diagram.png)

## Core Features
### 1. User
#### &emsp;&emsp;1-1: Create Account(Check unique Username&Email)
![alt text](/images/user_create.png)
#### &emsp;&emsp;1-2: Log In
![alt text](/images/user_login.png)
#### &emsp;&emsp;1-3: User MyPage(History of Q&A, Auctions, Items, Bidding)
![alt text](/images/user_detail.png)
#### &emsp;&emsp;1-3: Make Q&A
![alt text](/images/user_qna.png)
### 2. Item
#### &emsp;&emsp;2-1. Create Item
![alt text](/images/item_create.png)
### 3. Category
#### &emsp;&emsp;3-1. Create Category(Link to Parent Category)
![alt text](/images/category.png)
### 4. Auction
#### &emsp;&emsp;4-1. Create Auction
![alt text](/images/auction_open.png)
#### &emsp;&emsp;4-2. Different Auction Status
![alt text](/images/auction_status.png)
### 5. Bidding(Autobidding)
#### &emsp;&emsp;5-1. Fixed price/Anonymous Bidding
![alt text](/images/bidding.png)
#### &emsp;&emsp;5-2. Auto Bidding
![alt text](/images/bidding_auto.png)
#### &emsp;&emsp;5-3. Bidding Result
![alt text](/images/bidding_result.png)
### 6. Alert
#### &emsp;&emsp;6-1. Alert via Email(local SMPT server)
![alt text](/images/alert.png)
### 7. Browse
#### &emsp;&emsp;7-1. Shows auction status
![alt text](/images/browse_status.png)
#### &emsp;&emsp;7-2. Search with different criteria
![alt text](/images/browse_criteria.png)
### 8. Customer Representative
#### &emsp;&emsp;8-1. Answer Q&A
![alt text](/images/rep_qna.png)
#### &emsp;&emsp;8-2. Manage User Accounts
![alt text](/images/rep_user.png)
#### &emsp;&emsp;8-3. Edit User Accounts
![alt text](/images/rep_user_edit.png)
#### &emsp;&emsp;8-4. Manage Bids
![alt text](/images/rep_bid.png)
#### &emsp;&emsp;8-5. Manage Auctions
![alt text](/images/rep_auction.png)
### 9. Admin
#### &emsp;&emsp;9-1. Manage Customer Representative
![alt text](/images/admin_rep.png)
#### &emsp;&emsp;9-2. Create Customer Representative
![alt text](/images/admin_rep_create.png)
#### &emsp;&emsp;9-3. Manage Sales Report
![alt text](/images/admin_sales_report.png)

## Execution
1. Execute the application code.
```
python run.py
```
2. Turn on the local aiosmtpd server for email alerts
```
python -m aiosmtpd -n -l localhost:1025
```
3. Add an admin to the database. 
```
curl -X POST http://localhost:5000/admin/register \
     -H "Content-Type: application/json" \
     -d '{
           "username": "admin",
           "password": "1q2w3e4r",
           "email":    "admin@example.com"
         }'
```