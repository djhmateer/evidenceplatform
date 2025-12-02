
-- todo move to utf8mb4_0900_ai_ci once I know this is all working

CREATE DATABASE eplatform
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE eplatform;

CREATE USER 'doug'@'%' IDENTIFIED WITH caching_sha2_password BY 'password2';

GRANT ALL PRIVILEGES ON *.* TO 'doug'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;

create table user
(
    id       int auto_increment primary key,
    email    varchar(200) not null unique,
    password varchar(255) not null
); 
  
CREATE TABLE session (
    id INT AUTO_INCREMENT PRIMARY KEY,
    session_id VARCHAR(64) NOT NULL UNIQUE,
    user_id INT NOT NULL,
    expires_at DATETIME NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES user(id) ON DELETE CASCADE,
    INDEX idx_session_id (session_id),
    INDEX idx_expires_at (expires_at)
);

--  Seed initial user with password 1
INSERT INTO user (email, password) values ('davemateer@gmail.com', '$argon2id$v=19$m=65536,t=3,p=4$Fr2iPl70VyMWp9rlNgpooQ$XMzjKuMAJr91p1oZAm4PnNN/jaUUDrAqmljnArN6PqU');
