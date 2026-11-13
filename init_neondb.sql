-- Movements+ & FitTrack Database Initialization for NeonDB PostgreSQL
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Table: users
CREATE TABLE users (
	id UUID NOT NULL, 
	full_name VARCHAR(100) NOT NULL, 
	email VARCHAR(255) NOT NULL, 
	hashed_password VARCHAR(255) NOT NULL, 
	avatar_url VARCHAR(500), 
	age INTEGER NOT NULL, 
	weight_kg FLOAT NOT NULL, 
	height_cm FLOAT NOT NULL, 
	primary_goal VARCHAR(50) NOT NULL, 
	target_hr_bpm INTEGER NOT NULL, 
	is_active BOOLEAN NOT NULL, 
	is_onboarded BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id)
);

-- Table: daily_vitals
CREATE TABLE daily_vitals (
	id SERIAL NOT NULL, 
	user_id UUID NOT NULL, 
	date DATE NOT NULL, 
	agenda_title VARCHAR(100) NOT NULL, 
	steps_count INTEGER NOT NULL, 
	weight_kg FLOAT NOT NULL, 
	weight_status VARCHAR(50) NOT NULL, 
	latest_hr_bpm INTEGER NOT NULL, 
	hr_status VARCHAR(50) NOT NULL, 
	body_composition_pct FLOAT NOT NULL, 
	body_comp_badge VARCHAR(50) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- Table: heart_rate_analytics
CREATE TABLE heart_rate_analytics (
	id SERIAL NOT NULL, 
	user_id UUID NOT NULL, 
	recorded_date DATE NOT NULL, 
	slot_label VARCHAR(50) NOT NULL, 
	bpm_value INTEGER NOT NULL, 
	zone_type VARCHAR(50) NOT NULL, 
	is_peak BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- Table: nutrition_logs
CREATE TABLE nutrition_logs (
	id SERIAL NOT NULL, 
	user_id UUID NOT NULL, 
	date DATE NOT NULL, 
	calories_consumed INTEGER NOT NULL, 
	calories_goal INTEGER NOT NULL, 
	protein_g INTEGER NOT NULL, 
	carbs_g INTEGER NOT NULL, 
	fats_g INTEGER NOT NULL, 
	water_liters FLOAT NOT NULL, 
	water_goal_liters FLOAT NOT NULL, 
	metabolic_score_pct INTEGER NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- Table: sleep_zone_benchmarks
CREATE TABLE sleep_zone_benchmarks (
	id SERIAL NOT NULL, 
	user_id UUID NOT NULL, 
	recorded_date DATE NOT NULL, 
	light_pct VARCHAR(30) NOT NULL, 
	rem_pct VARCHAR(30) NOT NULL, 
	deep_pct VARCHAR(30) NOT NULL, 
	awake_pct VARCHAR(30) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- Table: workout_sessions
CREATE TABLE workout_sessions (
	id SERIAL NOT NULL, 
	user_id UUID NOT NULL, 
	title VARCHAR(100) NOT NULL, 
	category VARCHAR(50) NOT NULL, 
	progress_pct INTEGER NOT NULL, 
	duration_seconds INTEGER NOT NULL, 
	target_duration_seconds INTEGER NOT NULL, 
	distance_km FLOAT NOT NULL, 
	pace_str VARCHAR(50) NOT NULL, 
	avg_hr_bpm INTEGER NOT NULL, 
	calories_burned INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

-- Table: meal_entries
CREATE TABLE meal_entries (
	id SERIAL NOT NULL, 
	nutrition_log_id INTEGER, 
	user_id UUID NOT NULL, 
	meal_type VARCHAR(50) NOT NULL, 
	title VARCHAR(150) NOT NULL, 
	calories INTEGER NOT NULL, 
	protein_g INTEGER NOT NULL, 
	logged_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(nutrition_log_id) REFERENCES nutrition_logs (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);

