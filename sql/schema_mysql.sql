-- Cria a base de dados e define as tabelas necessárias para a aplicação
-- Inclui constraints, índices e tipos de dados apropriados para cada coluna

DROP DATABASE IF EXISTS studyspot;
CREATE DATABASE studyspot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE studyspot;

-- Tabela: User
-- Guarda informações sobre os utilizadores ativos que fazem reviews
DROP TABLE IF EXISTS User;
CREATE TABLE User (
    user_id CHAR(22) NOT NULL,
    name VARCHAR(100) NOT NULL,
    review_count INT NOT NULL DEFAULT 0,
    yelping_since DATETIME NOT NULL,
    average_stars DECIMAL(3,2) NULL,
    PRIMARY KEY (user_id),
    CONSTRAINT chk_user_avg_stars CHECK (average_stars BETWEEN 0.0 AND 5.0)
) ENGINE=InnoDB;

-- Tabela: Business
-- Entidade principal que representa os locais de estudo (cafes, bakeries, coffee shops)
-- Inclui POINT geográfico com Spatial Index para queries de distância
DROP TABLE IF EXISTS Business;
CREATE TABLE Business (
    business_id CHAR(22) NOT NULL,
    name VARCHAR(255) NOT NULL,
    address VARCHAR(255) NOT NULL,
    city VARCHAR(100) NOT NULL,
    state VARCHAR(3) NOT NULL,
    postal_code VARCHAR(10) NOT NULL,
    location POINT SRID 4326 NOT NULL,
    stars DECIMAL(2,1) NOT NULL,
    review_count INT NOT NULL DEFAULT 0,
    is_open BOOLEAN NOT NULL,
    PRIMARY KEY (business_id),
    SPATIAL INDEX idx_business_location (location),
    CONSTRAINT chk_business_stars CHECK (stars BETWEEN 1.0 AND 5.0)
) ENGINE=InnoDB;

-- Tabela: Category
-- Tabela lookup para categorias de businesses
DROP TABLE IF EXISTS Category;
CREATE TABLE Category (
    category_id INT AUTO_INCREMENT NOT NULL,
    name VARCHAR(100) NOT NULL,
    PRIMARY KEY (category_id),
    CONSTRAINT uq_category_name UNIQUE (name)
) ENGINE=InnoDB;

-- Tabela: BusinessCategory (Joint Table N:M)
-- Conecta venues com multiplas categorias
DROP TABLE IF EXISTS BusinessCategory;
CREATE TABLE BusinessCategory (
    business_id CHAR(22) NOT NULL,
    category_id INT NOT NULL,
    PRIMARY KEY (business_id, category_id),
    FOREIGN KEY (business_id) REFERENCES Business(business_id) ON DELETE CASCADE,
    FOREIGN KEY (category_id) REFERENCES Category(category_id) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- Tabela: Business_Amenities
-- Separa as amenities dos businesses para permitir queries mais eficientes
DROP TABLE IF EXISTS Business_Amenities;
CREATE TABLE Business_Amenities (
    business_id CHAR(22) NOT NULL,
    wifi ENUM('free', 'paid', 'no') NULL,
    noise_level ENUM('quiet', 'average', 'loud', 'very_loud') NULL,
    outlet_mentions INT NOT NULL DEFAULT 0,
    PRIMARY KEY (business_id),
    FOREIGN KEY (business_id) REFERENCES Business(business_id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Tabela: Review
-- Guarda as reviews feitas pelos utilizadores sobre os businesses
DROP TABLE IF EXISTS Review;
CREATE TABLE Review (
    review_id CHAR(22) NOT NULL,
    business_id CHAR(22) NOT NULL,
    user_id CHAR(22) NOT NULL,
    stars TINYINT NOT NULL,
    useful INT NOT NULL DEFAULT 0,
    funny INT NOT NULL DEFAULT 0,
    cool INT NOT NULL DEFAULT 0,
    review_date DATETIME NOT NULL,
    text TEXT NOT NULL,
    mentions_wifi BOOLEAN NOT NULL DEFAULT FALSE,
    mentions_outlets BOOLEAN NOT NULL DEFAULT FALSE,
    mentions_pastry BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (review_id),
    FOREIGN KEY (business_id) REFERENCES Business(business_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES User(user_id) ON DELETE CASCADE,
    CONSTRAINT chk_review_stars CHECK (stars BETWEEN 1 AND 5)
) ENGINE=InnoDB; 
