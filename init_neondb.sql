-- FitTrack schema for NeonDB (PostgreSQL). Generated from the SQLAlchemy models.
-- The backend also creates these automatically on startup; this file is for manual setup.

CREATE TABLE IF NOT EXISTS users (
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
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email);
CREATE INDEX IF NOT EXISTS ix_users_id ON users (id);

CREATE TABLE IF NOT EXISTS daily_vitals (
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
	CONSTRAINT uq_daily_vitals_user_date UNIQUE (user_id, date), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_daily_vitals_date ON daily_vitals (date);
CREATE INDEX IF NOT EXISTS ix_daily_vitals_id ON daily_vitals (id);
CREATE INDEX IF NOT EXISTS ix_daily_vitals_user_id ON daily_vitals (user_id);

CREATE TABLE IF NOT EXISTS heart_rate_analytics (
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
CREATE INDEX IF NOT EXISTS ix_heart_rate_analytics_id ON heart_rate_analytics (id);
CREATE INDEX IF NOT EXISTS ix_heart_rate_analytics_recorded_date ON heart_rate_analytics (recorded_date);
CREATE INDEX IF NOT EXISTS ix_heart_rate_analytics_user_id ON heart_rate_analytics (user_id);

CREATE TABLE IF NOT EXISTS nutrition_logs (
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
	CONSTRAINT uq_nutrition_logs_user_date UNIQUE (user_id, date), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_nutrition_logs_date ON nutrition_logs (date);
CREATE INDEX IF NOT EXISTS ix_nutrition_logs_id ON nutrition_logs (id);
CREATE INDEX IF NOT EXISTS ix_nutrition_logs_user_id ON nutrition_logs (user_id);

CREATE TABLE IF NOT EXISTS sleep_zone_benchmarks (
	id SERIAL NOT NULL, 
	user_id UUID NOT NULL, 
	recorded_date DATE NOT NULL, 
	light_pct VARCHAR(30) NOT NULL, 
	rem_pct VARCHAR(30) NOT NULL, 
	deep_pct VARCHAR(30) NOT NULL, 
	awake_pct VARCHAR(30) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_sleep_benchmarks_user_date UNIQUE (user_id, recorded_date), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_sleep_zone_benchmarks_id ON sleep_zone_benchmarks (id);
CREATE INDEX IF NOT EXISTS ix_sleep_zone_benchmarks_recorded_date ON sleep_zone_benchmarks (recorded_date);
CREATE INDEX IF NOT EXISTS ix_sleep_zone_benchmarks_user_id ON sleep_zone_benchmarks (user_id);

CREATE TABLE IF NOT EXISTS workout_sessions (
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
	steps_count INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_workout_sessions_id ON workout_sessions (id);
CREATE INDEX IF NOT EXISTS ix_workout_sessions_user_id ON workout_sessions (user_id);

CREATE TABLE IF NOT EXISTS meal_entries (
	id SERIAL NOT NULL, 
	nutrition_log_id INTEGER, 
	user_id UUID NOT NULL, 
	meal_type VARCHAR(50) NOT NULL, 
	title VARCHAR(150) NOT NULL, 
	calories INTEGER NOT NULL, 
	protein_g INTEGER NOT NULL, 
	carbs_g INTEGER NOT NULL, 
	fats_g INTEGER NOT NULL, 
	logged_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(nutrition_log_id) REFERENCES nutrition_logs (id) ON DELETE CASCADE, 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_meal_entries_id ON meal_entries (id);
CREATE INDEX IF NOT EXISTS ix_meal_entries_nutrition_log_id ON meal_entries (nutrition_log_id);
CREATE INDEX IF NOT EXISTS ix_meal_entries_user_id ON meal_entries (user_id);

-- Sleep tracking (one night per user per wake-up day)
CREATE TABLE IF NOT EXISTS sleep_sessions (
	id SERIAL NOT NULL, 
	user_id UUID NOT NULL, 
	date DATE NOT NULL, 
	start_local TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	end_local TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
	asleep_min INTEGER NOT NULL, 
	awake_min INTEGER, 
	light_min INTEGER, 
	deep_min INTEGER, 
	rem_min INTEGER, 
	source VARCHAR(20) NOT NULL, 
	rating INTEGER, 
	confirmed BOOLEAN NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_sleep_sessions_user_date UNIQUE (user_id, date), 
	FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_sleep_sessions_date ON sleep_sessions (date);
CREATE INDEX IF NOT EXISTS ix_sleep_sessions_id ON sleep_sessions (id);
CREATE INDEX IF NOT EXISTS ix_sleep_sessions_user_id ON sleep_sessions (user_id);
