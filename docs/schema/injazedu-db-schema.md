# Database Schema

## Summary

* **Database driver:** MySQL (`DB_CONNECTION=mysql` in `.env`; `config/database.php` default = `mysql`). All types below are given in MySQL terms.
* **Total discovered tables:** 49
  * 46 created by project migrations in `database/migrations/`
  * 3 created by the vendored `laravel/telescope` migration (auto-loaded by `TelescopeServiceProvider`)
* **Total confirmed foreign keys (migration-defined):** 51
  * 50 in project migrations
  * 1 in the Telescope vendor migration (`telescope_entries_tags.entry_uuid`)
* **Pivot / junction tables:** 10 — `course_user`, `book_course`, `course_order`, `book_order`, `coupon_course`, `question_result`, `user_permissions`, `user_roles`, `role_permissions`, plus package-owned `telescope_entries_tags`
* **Custom table prefix:** none (`'prefix' => ''`)
* **Multiple connections:** no — the application uses only the default `mysql` connection (`audits` and Telescope resolve to `config('database.default')`)
* **Tables whose schema could not be fully confirmed:** none among migration-defined tables. Note: this document describes the *migration-defined* schema, not a dump of the live database (no SQL dump exists in the repo).

### Spatie Permission note (important)

`config/permission.php` **customizes** the package table names and morph key. The migration
`2021_12_09_004133_create_permission_tables.php` reads that config, so the actual tables are:

| Config key                        | Value              |
| --------------------------------- | ------------------ |
| `roles`                           | `roles`            |
| `permissions`                     | `permissions`      |
| `model_has_permissions`           | `user_permissions` |
| `model_has_roles`                 | `user_roles`       |
| `role_has_permissions`            | `role_permissions` |
| `column_names.model_morph_key`    | `user_id`          |
| `teams`                           | `false`            |

---

## Table: `users`

### Columns

| Column                  | Type            | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ----------------------- | --------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id                      | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| name                    | VARCHAR         | 255                | No       | —       | —           | —              |
| email                   | VARCHAR         | 255                | No       | —       | UNIQUE      | —              |
| phone                   | VARCHAR         | 255                | Yes      | NULL    | —           | —              |
| password                | VARCHAR         | 255                | No       | —       | —           | —              |
| gender                  | VARCHAR         | 255                | Yes      | NULL    | —           | —              |
| interested_course       | INT             | —                  | Yes      | NULL    | —           | No DB FK       |
| image                   | VARCHAR         | 255                | Yes      | NULL    | —           | —              |
| summary                 | TEXT            | —                  | Yes      | NULL    | —           | —              |
| job_title               | VARCHAR         | 255                | Yes      | NULL    | —           | —              |
| twitter_account         | VARCHAR         | 255                | Yes      | NULL    | —           | —              |
| facebook_account        | VARCHAR         | 255                | Yes      | NULL    | —           | —              |
| linkedin_account        | VARCHAR         | 255                | Yes      | NULL    | —           | —              |
| status                  | INT             | —                  | No       | 1       | —           | —              |
| email_verified_at       | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| remember_token          | VARCHAR         | 100                | Yes      | NULL    | —           | —              |
| deleted_at              | TIMESTAMP       | —                  | Yes      | NULL    | —           | Soft delete    |
| created_at              | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| updated_at              | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| fcm_token               | VARCHAR         | 255                | Yes      | NULL    | —           | Added 2023-01  |
| notification_permission | TINYINT(1)      | —                  | No       | 0       | —           | Added 2023-02  |

### Foreign Keys

None defined at the database level on this table.

### Indexes

| Index              | Columns | Type   |
| ------------------ | ------- | ------ |
| users_email_unique | email   | UNIQUE |

### Eloquent Relationships

| Model | Relationship  | Related Model   | Foreign/Pivot Key                       |
| ----- | ------------- | --------------- | --------------------------------------- |
| User  | hasMany       | SocialProvider  | social_providers.user_id                |
| User  | belongsToMany | Course          | `course_user` (user_id / course_id)     |
| User  | hasMany       | Order           | orders.user_id                          |
| User  | hasMany       | Result          | results.user_id                         |
| User  | morphToMany*  | Role/Permission | via Spatie `HasRoles` trait (`user_roles`, `user_permissions`) |

### Source

* `database/migrations/2014_10_12_000000_create_users_table.php`
* `database/migrations/2023_01_30_224155_add_culomn_to_users.php` (adds `fcm_token`)
* `database/migrations/2023_02_24_153911_add_culomn_to_users.php` (adds `notification_permission`)
* `app/Models/User.php`

---

## Table: `password_resets`

### Columns

| Column     | Type      | Length / Precision | Nullable | Default | Key / Index | Extra |
| ---------- | --------- | ------------------ | -------- | ------- | ----------- | ----- |
| email      | VARCHAR   | 255                | No       | —       | INDEX       | —     |
| token      | VARCHAR   | 255                | No       | —       | —           | —     |
| created_at | TIMESTAMP | —                  | Yes      | NULL    | —           | —     |

No primary key. Laravel default password-reset table.

### Source

* `database/migrations/2014_10_12_100000_create_password_resets_table.php`

---

## Table: `failed_jobs`

### Columns

| Column     | Type            | Length / Precision | Nullable | Default            | Key / Index | Extra          |
| ---------- | --------------- | ------------------ | -------- | ------------------ | ----------- | -------------- |
| id         | BIGINT UNSIGNED | —                  | No       | —                  | PRIMARY     | AUTO_INCREMENT |
| uuid       | VARCHAR         | 255                | No       | —                  | UNIQUE      | —              |
| connection | TEXT            | —                  | No       | —                  | —           | —              |
| queue      | TEXT            | —                  | No       | —                  | —           | —              |
| payload    | LONGTEXT        | —                  | No       | —                  | —           | —              |
| exception  | LONGTEXT        | —                  | No       | —                  | —           | —              |
| failed_at  | TIMESTAMP       | —                  | No       | CURRENT_TIMESTAMP  | —           | useCurrent()   |

### Source

* `database/migrations/2019_08_19_000000_create_failed_jobs_table.php`

---

## Table: `personal_access_tokens`

Sanctum token table.

### Columns

| Column         | Type            | Length / Precision | Nullable | Default | Key / Index         | Extra          |
| -------------- | --------------- | ------------------ | -------- | ------- | ------------------- | -------------- |
| id             | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY             | AUTO_INCREMENT |
| tokenable_type | VARCHAR         | 255                | No       | —       | INDEX (composite)   | morphs()       |
| tokenable_id   | BIGINT UNSIGNED | —                  | No       | —       | INDEX (composite)   | morphs()       |
| name           | VARCHAR         | 255                | No       | —       | —                   | —              |
| token          | VARCHAR         | 64                 | No       | —       | UNIQUE              | —              |
| abilities      | TEXT            | —                  | Yes      | NULL    | —                   | —              |
| last_used_at   | TIMESTAMP       | —                  | Yes      | NULL    | —                   | —              |
| created_at     | TIMESTAMP       | —                  | Yes      | NULL    | —                   | —              |
| updated_at     | TIMESTAMP       | —                  | Yes      | NULL    | —                   | —              |

### Indexes

| Index                                     | Columns                      | Type   |
| ----------------------------------------- | ---------------------------- | ------ |
| personal_access_tokens_tokenable_*_index  | tokenable_type, tokenable_id | INDEX  |
| personal_access_tokens_token_unique       | token                        | UNIQUE |

### Source

* `database/migrations/2019_12_14_000001_create_personal_access_tokens_table.php`

---

## Table: `permissions` (Spatie)

### Columns

| Column     | Type            | Length / Precision | Nullable | Default | Key / Index       | Extra          |
| ---------- | --------------- | ------------------ | -------- | ------- | ----------------- | -------------- |
| id         | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY           | AUTO_INCREMENT |
| name       | VARCHAR         | 125                | No       | —       | UNIQUE (composite)| —              |
| guard_name | VARCHAR         | 125                | No       | —       | UNIQUE (composite)| —              |
| created_at | TIMESTAMP       | —                  | Yes      | NULL    | —                 | —              |
| updated_at | TIMESTAMP       | —                  | Yes      | NULL    | —                 | —              |

### Indexes

| Index                         | Columns           | Type   |
| ----------------------------- | ----------------- | ------ |
| permissions_name_guard_name_unique | name, guard_name | UNIQUE |

### Source

* `database/migrations/2021_12_09_004133_create_permission_tables.php`
* `config/permission.php`

---

## Table: `roles` (Spatie)

### Columns

| Column     | Type            | Length / Precision | Nullable | Default | Key / Index       | Extra          |
| ---------- | --------------- | ------------------ | -------- | ------- | ----------------- | -------------- |
| id         | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY           | AUTO_INCREMENT |
| name       | VARCHAR         | 125                | No       | —       | UNIQUE (composite)| —              |
| guard_name | VARCHAR         | 125                | No       | —       | UNIQUE (composite)| —              |
| created_at | TIMESTAMP       | —                  | Yes      | NULL    | —                 | —              |
| updated_at | TIMESTAMP       | —                  | Yes      | NULL    | —                 | —              |

(`teams` is disabled in config, so no `team_id` column.)

### Indexes

| Index                      | Columns           | Type   |
| -------------------------- | ----------------- | ------ |
| roles_name_guard_name_unique | name, guard_name | UNIQUE |

### Source

* `database/migrations/2021_12_09_004133_create_permission_tables.php`
* `config/permission.php`

---

## Table: `user_permissions` (Spatie `model_has_permissions`, renamed via config)

Pivot between models (users) and permissions.

### Columns

| Column        | Type            | Length / Precision | Nullable | Default | Key / Index         | Extra |
| ------------- | --------------- | ------------------ | -------- | ------- | ------------------- | ----- |
| permission_id | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY (composite) | —     |
| model_type    | VARCHAR         | 255                | No       | —       | PRIMARY (composite) | —     |
| user_id       | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY (composite) | INDEX (composite with model_type) |

### Foreign Keys

| Column        | References     | On Delete | On Update |
| ------------- | -------------- | --------- | --------- |
| permission_id | permissions.id | CASCADE   | —         |

### Indexes

| Index                                          | Columns                              | Type    |
| ---------------------------------------------- | ------------------------------------ | ------- |
| model_has_permissions_permission_model_type_primary | permission_id, user_id, model_type | PRIMARY |
| model_has_permissions_model_id_model_type_index     | user_id, model_type                | INDEX   |

### Source

* `database/migrations/2021_12_09_004133_create_permission_tables.php`
* `config/permission.php` (`model_has_permissions` => `user_permissions`, `model_morph_key` => `user_id`)

---

## Table: `user_roles` (Spatie `model_has_roles`, renamed via config)

### Columns

| Column     | Type            | Length / Precision | Nullable | Default | Key / Index         | Extra |
| ---------- | --------------- | ------------------ | -------- | ------- | ------------------- | ----- |
| role_id    | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY (composite) | —     |
| model_type | VARCHAR         | 255                | No       | —       | PRIMARY (composite) | —     |
| user_id    | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY (composite) | INDEX (composite with model_type) |

### Foreign Keys

| Column  | References | On Delete | On Update |
| ------- | ---------- | --------- | --------- |
| role_id | roles.id   | CASCADE   | —         |

### Indexes

| Index                                  | Columns                      | Type    |
| -------------------------------------- | ---------------------------- | ------- |
| model_has_roles_role_model_type_primary    | role_id, user_id, model_type | PRIMARY |
| model_has_roles_model_id_model_type_index  | user_id, model_type          | INDEX   |

### Source

* `database/migrations/2021_12_09_004133_create_permission_tables.php`
* `config/permission.php` (`model_has_roles` => `user_roles`)

---

## Table: `role_permissions` (Spatie `role_has_permissions`, renamed via config)

### Columns

| Column        | Type            | Length / Precision | Nullable | Default | Key / Index         | Extra |
| ------------- | --------------- | ------------------ | -------- | ------- | ------------------- | ----- |
| permission_id | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY (composite) | —     |
| role_id       | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY (composite) | —     |

### Foreign Keys

| Column        | References     | On Delete | On Update |
| ------------- | -------------- | --------- | --------- |
| permission_id | permissions.id | CASCADE   | —         |
| role_id       | roles.id       | CASCADE   | —         |

### Indexes

| Index                                            | Columns                 | Type    |
| ------------------------------------------------ | ----------------------- | ------- |
| role_has_permissions_permission_id_role_id_primary | permission_id, role_id | PRIMARY |

### Source

* `database/migrations/2021_12_09_004133_create_permission_tables.php`
* `config/permission.php` (`role_has_permissions` => `role_permissions`)

---

## Table: `zoom_users`

### Columns

| Column     | Type             | Length / Precision     | Nullable | Default     | Key / Index | Extra                        |
| ---------- | ---------------- | ---------------------- | -------- | ----------- | ----------- | ---------------------------- |
| id         | BIGINT UNSIGNED  | —                      | No       | —           | PRIMARY     | AUTO_INCREMENT               |
| zoom_email | VARCHAR          | 255                    | No       | —           | —           | COMMENT 'User Email from zoom' |
| zoom_id    | VARCHAR          | 255                    | No       | —           | —           | COMMENT 'User Id from zoom'  |
| type       | ENUM             | ('1','2','3','99')     | No       | '1'         | —           | Values defined as ints 1,2,3,99 |
| first_name | VARCHAR          | 255                    | Yes      | NULL        | —           | —                            |
| last_name  | VARCHAR          | 255                    | Yes      | NULL        | —           | —                            |
| status     | ENUM             | ('activate','deactivate') | No    | 'activate'  | —           | —                            |
| registered | TINYINT(1)       | —                      | No       | 0           | —           | —                            |
| user_id    | BIGINT UNSIGNED  | —                      | Yes      | NULL        | INDEX (FK)  | —                            |
| deleted_at | TIMESTAMP        | —                      | Yes      | NULL        | —           | Soft delete                  |
| created_at | TIMESTAMP        | —                      | Yes      | NULL        | —           | —                            |
| updated_at | TIMESTAMP        | —                      | Yes      | NULL        | —           | —                            |

### Foreign Keys

| Column  | References | On Delete | On Update |
| ------- | ---------- | --------- | --------- |
| user_id | users.id   | CASCADE   | —         |

### Eloquent Relationships

None declared in `app/Models/ZoomUser.php` (model has no `user()` relation despite the FK).

### Source

* `database/migrations/2021_12_11_133920_create_zoom_users_table.php`
* `app/Models/ZoomUser.php`

---

## Table: `categories`

### Columns

| Column           | Type            | Length / Precision | Nullable | Default | Key / Index | Extra             |
| ---------------- | --------------- | ------------------ | -------- | ------- | ----------- | ----------------- |
| id               | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT    |
| name             | VARCHAR         | 255                | No       | —       | —           | —                 |
| slug             | VARCHAR         | 255                | Yes      | NULL    | UNIQUE      | —                 |
| sorte_order      | INT             | —                  | Yes      | NULL    | —           | (sic, "sorte")    |
| image            | VARCHAR         | 255                | Yes      | NULL    | —           | —                 |
| meta_title       | VARCHAR         | 255                | Yes      | NULL    | —           | —                 |
| meta_description | VARCHAR         | 255                | Yes      | NULL    | —           | —                 |
| parent_id        | INT             | —                  | Yes      | NULL    | —           | Self-ref; no DB FK |
| courses_card     | VARCHAR         | 255                | Yes      | NULL    | —           | —                 |
| quizzes_card     | VARCHAR         | 255                | Yes      | NULL    | —           | —                 |
| events_card      | VARCHAR         | 255                | Yes      | NULL    | —           | —                 |
| deleted_at       | TIMESTAMP       | —                  | Yes      | NULL    | —           | Soft delete       |
| created_at       | TIMESTAMP       | —                  | Yes      | NULL    | —           | —                 |
| updated_at       | TIMESTAMP       | —                  | Yes      | NULL    | —           | —                 |
| mobile_image     | VARCHAR         | 255                | Yes      | NULL    | —           | Added 2022-10     |

### Indexes

| Index                  | Columns | Type   |
| ---------------------- | ------- | ------ |
| categories_slug_unique | slug    | UNIQUE |

### Eloquent Relationships

| Model    | Relationship | Related Model | Foreign/Pivot Key      |
| -------- | ------------ | ------------- | ---------------------- |
| Category | hasMany      | Category      | parent_id (children)   |
| Category | belongsTo    | Category      | parent_id (parent)     |
| Category | hasMany      | Course        | courses.category_id    |
| Category | hasMany      | Event         | events.category_id     |
| Category | hasMany      | Quiz          | quizzes.category_id    |
| Category | hasMany      | CourseRequest | course_requests.category_id |

### Source

* `database/migrations/2021_12_26_154424_create_categories_table.php`
* `database/migrations/2022_10_07_193010_add_mobile_image_channel_to_categories_table.php` (adds `mobile_image`)
* `app/Models/Category.php`

---

## Table: `courses`

### Columns

| Column            | Type            | Length / Precision | Nullable | Default | Key / Index | Extra                     |
| ----------------- | --------------- | ------------------ | -------- | ------- | ----------- | ------------------------- |
| id                | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT            |
| name              | VARCHAR         | 255                | No       | —       | —           | —                         |
| slug              | VARCHAR         | 255                | Yes      | NULL    | UNIQUE      | —                         |
| sorte_order       | INT             | —                  | Yes      | NULL    | —           | —                         |
| price             | DECIMAL         | (8,2)              | No       | —       | —           | —                         |
| discount          | DECIMAL         | (8,2)              | Yes      | NULL    | —           | —                         |
| description       | TEXT            | —                  | No       | —       | —           | —                         |
| meta_title        | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| meta_description  | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| image             | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| poster            | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| schedule          | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| start_date        | DATE            | —                  | No       | —       | —           | —                         |
| start_date_hijri  | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| exam_date         | DATE            | —                  | Yes      | NULL    | —           | Added 2023-12, after start_date_hijri |
| live_days         | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| live_time         | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| course_conditions | TEXT            | —                  | Yes      | NULL    | —           | —                         |
| intro             | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| expire_duration   | INT             | —                  | No       | —       | —           | —                         |
| status            | TINYINT(1)      | —                  | No       | 1       | —           | —                         |
| telegram_group    | VARCHAR         | 255                | Yes      | NULL    | —           | Added 2022-04, after status |
| telegram_private  | VARCHAR         | 255                | Yes      | NULL    | —           | Added 2022-04             |
| telegram_channel  | VARCHAR         | 255                | Yes      | NULL    | —           | Added 2022-08, after telegram_private |
| category_id       | BIGINT UNSIGNED | —                  | No       | —       | INDEX (FK)  | —                         |
| deleted_at        | TIMESTAMP       | —                  | Yes      | NULL    | —           | Soft delete               |
| created_at        | TIMESTAMP       | —                  | Yes      | NULL    | —           | —                         |
| updated_at        | TIMESTAMP       | —                  | Yes      | NULL    | —           | —                         |

### Foreign Keys

| Column      | References     | On Delete | On Update |
| ----------- | -------------- | --------- | --------- |
| category_id | categories.id  | CASCADE   | —         |

### Indexes

| Index                          | Columns     | Type   |
| ------------------------------ | ----------- | ------ |
| courses_slug_unique            | slug        | UNIQUE |
| courses_category_id_foreign    | category_id | INDEX  |

### Eloquent Relationships

| Model  | Relationship  | Related Model | Foreign/Pivot Key                        |
| ------ | ------------- | ------------- | ---------------------------------------- |
| Course | belongsTo     | Category      | category_id                              |
| Course | hasMany       | Chapter       | chapters.course_id                       |
| Course | hasMany       | Book          | books.course_id                          |
| Course | belongsToMany | User          | `course_user` (course_id / user_id)      |
| Course | hasMany       | Quiz          | quizzes.course_id                        |
| Course | belongsToMany | Order         | `course_order` (course_id / order_id), withPivot `expiry_date` |
| Course | belongsToMany | Coupon        | `coupon_course` (default keys)           |

### Source

* `database/migrations/2021_12_28_135155_create_courses_table.php`
* `database/migrations/2022_04_27_053601_add_telegram_to_courses_table.php`
* `database/migrations/2022_08_09_002618_add_telegram_channel_to_courses_table.php`
* `database/migrations/2023_12_23_031838_add_exam_date_to_courses_table.php`
* `app/Models/Course.php`

---

## Table: `chapters`

### Columns

| Column      | Type            | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ----------- | --------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id          | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| title       | VARCHAR         | 255                | No       | —       | —           | —              |
| sorte_order | INT             | —                  | Yes      | NULL    | —           | —              |
| course_id   | BIGINT UNSIGNED | —                  | No       | —       | INDEX (FK)  | —              |
| deleted_at  | TIMESTAMP       | —                  | Yes      | NULL    | —           | Soft delete    |
| created_at  | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| updated_at  | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |

### Foreign Keys

| Column    | References | On Delete | On Update |
| --------- | ---------- | --------- | --------- |
| course_id | courses.id | CASCADE   | —         |

### Eloquent Relationships

| Model   | Relationship | Related Model | Foreign/Pivot Key   |
| ------- | ------------ | ------------- | ------------------- |
| Chapter | belongsTo    | Course        | course_id           |
| Chapter | hasMany      | Lecture       | lectures.chapter_id |

### Source

* `database/migrations/2022_02_24_164504_create_chapters_table.php`
* `app/Models/Chapter.php`

---

## Table: `lectures`

### Columns

| Column           | Type            | Length / Precision                     | Nullable | Default         | Key / Index | Extra                          |
| ---------------- | --------------- | -------------------------------------- | -------- | --------------- | ----------- | ------------------------------ |
| id               | BIGINT UNSIGNED | —                                      | No       | —               | PRIMARY     | AUTO_INCREMENT                 |
| topic            | VARCHAR         | 255                                    | No       | —               | —           | —                              |
| sorte_order      | INT             | —                                      | Yes      | NULL            | —           | —                              |
| start_time       | DATETIME        | —                                      | Yes      | NULL            | —           | —                              |
| start_date_hijri | VARCHAR         | 255                                    | Yes      | NULL            | —           | —                              |
| duration         | INT             | —                                      | Yes      | NULL            | —           | —                              |
| vimeo_id         | VARCHAR         | 255                                    | Yes      | NULL            | —           | —                              |
| book             | VARCHAR         | 255                                    | Yes      | NULL            | —           | —                              |
| zoom_start_url   | TEXT            | —                                      | Yes      | NULL            | —           | —                              |
| zoom_join_url    | VARCHAR         | 255                                    | Yes      | NULL            | —           | —                              |
| meeting_type     | VARCHAR         | 255                                    | No       | 'meeting'       | —           | Added 2022-07, after zoom_join_url |
| meeting_id       | VARCHAR         | 255                                    | Yes      | NULL            | —           | —                              |
| passcode         | VARCHAR         | 255                                    | Yes      | NULL            | —           | —                              |
| live             | TINYINT(1)      | —                                      | No       | 1               | —           | Added 2024-01, after passcode  |
| host             | VARCHAR         | 50                                     | Yes      | 'digitalocean'  | —           | Added 2024-09, after live      |
| bunny_id         | VARCHAR         | 255                                    | Yes      | NULL            | —           | Added 2024-09                  |
| youtube_id       | VARCHAR         | 255                                    | Yes      | NULL            | —           | Added 2024-12, after bunny_id  |
| upload_status    | ENUM            | ('pending','processing','completed','failed') | Yes | NULL       | —           | Added 2024-12                  |
| upload_error     | TEXT            | —                                      | Yes      | NULL            | —           | Added 2024-12                  |
| chapter_id       | BIGINT UNSIGNED | —                                      | No       | —               | INDEX (FK)  | —                              |
| deleted_at       | TIMESTAMP       | —                                      | Yes      | NULL            | —           | Soft delete                    |
| created_at       | TIMESTAMP       | —                                      | Yes      | NULL            | —           | —                              |
| updated_at       | TIMESTAMP       | —                                      | Yes      | NULL            | —           | —                              |

### Foreign Keys

| Column     | References  | On Delete | On Update |
| ---------- | ----------- | --------- | --------- |
| chapter_id | chapters.id | CASCADE   | —         |

### Eloquent Relationships

| Model   | Relationship | Related Model | Foreign/Pivot Key   |
| ------- | ------------ | ------------- | ------------------- |
| Lecture | belongsTo    | Chapter       | chapter_id          |
| Lecture | hasOne       | Quiz          | quizzes.lecture_id  |
| Lecture | hasMany      | Quiz (exam)   | quizzes.lecture_id  |

### Source

* `database/migrations/2022_02_24_164547_create_lectures_table.php`
* `database/migrations/2022_07_15_181908_add_meeting_type_to_lectures_table.php`
* `database/migrations/2024_01_30_192225_add_live_to_lectures_table.php`
* `database/migrations/2024_09_25_003050_add_host_to_lectures_table.php`
* `database/migrations/2024_12_27_000000_add_youtube_id_to_lectures_table.php`
* `app/Models/Lecture.php`

---

## Table: `course_user` (pivot)

### Columns

| Column    | Type            | Length / Precision | Nullable | Default | Key / Index | Extra |
| --------- | --------------- | ------------------ | -------- | ------- | ----------- | ----- |
| course_id | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —     |
| user_id   | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —     |

No primary key, no timestamps.

### Foreign Keys

| Column    | References | On Delete | On Update |
| --------- | ---------- | --------- | --------- |
| course_id | courses.id | CASCADE   | —         |
| user_id   | users.id   | CASCADE   | —         |

### Eloquent Relationships

| Model  | Relationship  | Related Model | Pivot Keys            |
| ------ | ------------- | ------------- | --------------------- |
| User   | belongsToMany | Course        | user_id / course_id   |
| Course | belongsToMany | User (trainers) | course_id / user_id |

### Source

* `database/migrations/2022_02_25_161118_create_course_user_table.php`

---

## Table: `books`

### Columns

| Column           | Type            | Length / Precision | Nullable | Default  | Key / Index | Extra                              |
| ---------------- | --------------- | ------------------ | -------- | -------- | ----------- | ---------------------------------- |
| id               | BIGINT UNSIGNED | —                  | No       | —        | PRIMARY     | AUTO_INCREMENT                     |
| title            | VARCHAR         | 255                | No       | —        | —           | —                                  |
| slug             | VARCHAR         | 255                | Yes      | NULL     | UNIQUE      | —                                  |
| sorte_order      | INT             | —                  | Yes      | NULL     | —           | —                                  |
| description      | VARCHAR         | 255                | Yes      | NULL     | —           | Defined as string, not text        |
| course_id        | BIGINT UNSIGNED | —                  | Yes      | NULL     | INDEX (FK)  | —                                  |
| price            | DECIMAL         | (8,2)              | No       | 0        | —           | Added 2023-08; changed 2023-10 to DEFAULT 0 |
| discount         | DECIMAL         | (8,2)              | No       | 0        | —           | Added 2023-08; changed 2023-10 to DEFAULT 0 (nullable dropped by `change()`) |
| status           | TINYINT(1)      | —                  | No       | 1        | —           | Added 2023-08                      |
| category_id      | BIGINT UNSIGNED | —                  | Yes      | NULL     | INDEX (FK)  | Added 2023-08                      |
| image            | VARCHAR         | 255                | No       | —        | —           | —                                  |
| type             | VARCHAR         | 255                | No       | 'course' | —           | Added 2023-10, after image         |
| file             | VARCHAR         | 255                | Yes      | NULL     | —           | Changed 2023-10 to nullable        |
| store_file       | VARCHAR         | 255                | Yes      | NULL     | —           | Added 2023-08, after file          |
| print_url        | VARCHAR         | 255                | Yes      | NULL     | —           | —                                  |
| meta_title       | VARCHAR         | 255                | Yes      | NULL     | —           | —                                  |
| meta_description | VARCHAR         | 255                | Yes      | NULL     | —           | —                                  |
| deleted_at       | TIMESTAMP       | —                  | Yes      | NULL     | —           | Soft delete                        |
| created_at       | TIMESTAMP       | —                  | Yes      | NULL     | —           | —                                  |
| updated_at       | TIMESTAMP       | —                  | Yes      | NULL     | —           | —                                  |

### Foreign Keys

| Column      | References    | On Delete | On Update |
| ----------- | ------------- | --------- | --------- |
| course_id   | courses.id    | CASCADE   | —         |
| category_id | categories.id | CASCADE   | —         |

### Indexes

| Index             | Columns | Type   |
| ----------------- | ------- | ------ |
| books_slug_unique | slug    | UNIQUE |

### Eloquent Relationships

| Model | Relationship  | Related Model | Foreign/Pivot Key                 |
| ----- | ------------- | ------------- | --------------------------------- |
| Book  | belongsTo     | Course        | course_id                         |
| Book  | belongsTo     | Category      | category_id                       |
| Book  | belongsToMany | Order         | `book_order` (book_id / order_id) |

### Source

* `database/migrations/2022_02_27_054902_create_books_table.php`
* `database/migrations/2023_08_01_174545_add_culomn_to_books_table.php` (price, discount, status, category_id)
* `database/migrations/2023_08_07_202009_add_store_file_to_books_table.php`
* `database/migrations/2023_10_21_030644_alter_file_in_books_table.php` (price/discount defaults, file nullable, adds `type`)
* `app/Models/Book.php`

---

## Table: `book_course` (pivot)

### Columns

| Column    | Type            | Length / Precision | Nullable | Default | Key / Index | Extra |
| --------- | --------------- | ------------------ | -------- | ------- | ----------- | ----- |
| book_id   | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —     |
| course_id | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —     |

No primary key, no timestamps. **Note:** no Eloquent `belongsToMany` currently uses this pivot in the inspected models (books relate to courses via `books.course_id`); it appears to be legacy/deprecated.

### Foreign Keys

| Column    | References | On Delete | On Update |
| --------- | ---------- | --------- | --------- |
| book_id   | books.id   | CASCADE   | —         |
| course_id | courses.id | CASCADE   | —         |

### Source

* `database/migrations/2022_02_28_161243_create_book_course_table.php`

---

## Table: `quizzes`

### Columns

| Column           | Type            | Length / Precision | Nullable | Default | Key / Index | Extra                       |
| ---------------- | --------------- | ------------------ | -------- | ------- | ----------- | --------------------------- |
| id               | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT              |
| name             | VARCHAR         | 255                | No       | —       | —           | —                           |
| slug             | VARCHAR         | 255                | Yes      | NULL    | UNIQUE      | —                           |
| description      | TEXT            | —                  | Yes      | NULL    | —           | —                           |
| image            | VARCHAR         | 255                | Yes      | NULL    | —           | —                           |
| meta_title       | VARCHAR         | 255                | Yes      | NULL    | —           | —                           |
| meta_description | VARCHAR         | 255                | Yes      | NULL    | —           | —                           |
| sort_order       | INT             | —                  | Yes      | 1       | —           | —                           |
| status           | TINYINT(1)      | —                  | No       | 1       | —           | —                           |
| user_id          | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —                           |
| category_id      | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —                           |
| course_id        | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —                           |
| lecture_id       | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —                           |
| hint             | VARCHAR         | 255                | Yes      | NULL    | —           | Added 2024-08, after lecture_id |
| duration         | INT             | —                  | No       | 10      | —           | Added 2023-01               |
| created_at       | TIMESTAMP       | —                  | Yes      | NULL    | —           | —                           |
| updated_at       | TIMESTAMP       | —                  | Yes      | NULL    | —           | —                           |
| deleted_at       | TIMESTAMP       | —                  | Yes      | NULL    | —           | Soft delete                 |

### Foreign Keys

| Column      | References    | On Delete | On Update |
| ----------- | ------------- | --------- | --------- |
| user_id     | users.id      | CASCADE   | —         |
| category_id | categories.id | CASCADE   | —         |
| course_id   | courses.id    | CASCADE   | —         |
| lecture_id  | lectures.id   | CASCADE   | —         |

### Indexes

| Index               | Columns | Type   |
| ------------------- | ------- | ------ |
| quizzes_slug_unique | slug    | UNIQUE |

### Eloquent Relationships

| Model | Relationship | Related Model | Foreign/Pivot Key     |
| ----- | ------------ | ------------- | --------------------- |
| Quiz  | belongsTo    | Category      | category_id           |
| Quiz  | belongsTo    | Course        | course_id             |
| Quiz  | belongsTo    | Lecture       | lecture_id            |
| Quiz  | belongsTo    | User          | user_id               |
| Quiz  | hasMany      | Section       | sections.quiz_id      |
| Quiz  | hasMany      | Result        | results.quiz_id       |

### Source

* `database/migrations/2022_03_12_162933_create_quizzes_table.php`
* `database/migrations/2023_01_23_211924_add_culomn_to_quizzes.php` (adds `duration`)
* `database/migrations/2024_08_22_021649_add_hint_to_quizzes_table.php`
* `app/Models/Quiz.php`

---

## Table: `sections`

### Columns

| Column      | Type            | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ----------- | --------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id          | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| name        | VARCHAR         | 255                | Yes      | NULL    | —           | —              |
| description | TEXT            | —                  | Yes      | NULL    | —           | —              |
| quiz_id     | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —              |
| order       | INT             | —                  | No       | 1       | —           | —              |
| created_at  | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| updated_at  | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| deleted_at  | TIMESTAMP       | —                  | Yes      | NULL    | —           | Soft delete    |

### Foreign Keys

| Column  | References | On Delete | On Update |
| ------- | ---------- | --------- | --------- |
| quiz_id | quizzes.id | CASCADE   | —         |

### Eloquent Relationships

| Model   | Relationship | Related Model | Foreign/Pivot Key        |
| ------- | ------------ | ------------- | ------------------------ |
| Section | belongsTo    | Quiz          | quiz_id                  |
| Section | hasMany      | Question      | questions.section_id     |
| Section | hasOne       | QuizFile      | quiz_files.section_id    |

### Source

* `database/migrations/2022_03_12_162952_create_sections_table.php`
* `app/Models/Section.php`

---

## Table: `questions`

### Columns

| Column      | Type            | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ----------- | --------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id          | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| name        | LONGTEXT        | —                  | No       | —       | —           | —              |
| description | TEXT            | —                  | Yes      | NULL    | —           | —              |
| hint        | TEXT            | —                  | Yes      | NULL    | —           | —              |
| order       | INT             | —                  | No       | 1       | —           | —              |
| section_id  | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —              |
| created_at  | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| updated_at  | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| deleted_at  | TIMESTAMP       | —                  | Yes      | NULL    | —           | Soft delete    |

### Foreign Keys

| Column     | References  | On Delete | On Update |
| ---------- | ----------- | --------- | --------- |
| section_id | sections.id | CASCADE   | —         |

### Eloquent Relationships

| Model    | Relationship  | Related Model | Foreign/Pivot Key                                   |
| -------- | ------------- | ------------- | --------------------------------------------------- |
| Question | hasMany       | Option        | options.question_id                                 |
| Question | hasOne        | QuizFile      | quiz_files.question_id                              |
| Result   | belongsToMany | Question      | `question_result` (result_id / question_id), withPivot option_id, points |

### Source

* `database/migrations/2022_03_12_172109_create_questions_table.php`
* `app/Models/Question.php`

---

## Table: `options`

### Columns

| Column      | Type            | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ----------- | --------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id          | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| name        | VARCHAR         | 255                | No       | —       | —           | —              |
| points      | INT             | —                  | No       | 0       | —           | —              |
| order       | INT             | —                  | No       | 0       | —           | —              |
| question_id | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —              |
| created_at  | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| updated_at  | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| deleted_at  | TIMESTAMP       | —                  | Yes      | NULL    | —           | Soft delete    |

### Foreign Keys

| Column      | References   | On Delete | On Update |
| ----------- | ------------ | --------- | --------- |
| question_id | questions.id | CASCADE   | —         |

### Eloquent Relationships

None declared on `Option` itself; inverse is `Question::options()` (hasMany).

### Source

* `database/migrations/2022_03_12_172829_create_options_table.php`
* `app/Models/Option.php`

---

## Table: `quiz_files`

### Columns

| Column      | Type            | Length / Precision          | Nullable | Default | Key / Index | Extra          |
| ----------- | --------------- | --------------------------- | -------- | ------- | ----------- | -------------- |
| id          | BIGINT UNSIGNED | —                           | No       | —       | PRIMARY     | AUTO_INCREMENT |
| type        | ENUM            | ('video','image','audio')   | No       | —       | —           | —              |
| path        | VARCHAR         | 255                         | Yes      | NULL    | —           | —              |
| section_id  | BIGINT UNSIGNED | —                           | Yes      | NULL    | INDEX (FK)  | —              |
| question_id | BIGINT UNSIGNED | —                           | Yes      | NULL    | INDEX (FK)  | —              |
| created_at  | TIMESTAMP       | —                           | Yes      | NULL    | —           | —              |
| updated_at  | TIMESTAMP       | —                           | Yes      | NULL    | —           | —              |

(No soft deletes on this table; `QuizFile` model also has no SoftDeletes.)

### Foreign Keys

| Column      | References   | On Delete | On Update |
| ----------- | ------------ | --------- | --------- |
| section_id  | sections.id  | CASCADE   | —         |
| question_id | questions.id | CASCADE   | —         |

### Eloquent Relationships

Inverse relations only: `Section::file()` and `Question::file()` (hasOne).

### Source

* `database/migrations/2022_03_13_171111_create_quiz_files_table.php`
* `app/Models/QuizFile.php`

---

## Table: `events`

### Columns

| Column           | Type            | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ---------------- | --------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id               | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| name             | VARCHAR         | 255                | No       | —       | —           | —              |
| slug             | VARCHAR         | 255                | Yes      | NULL    | UNIQUE      | —              |
| sorte_order      | INT             | —                  | Yes      | NULL    | —           | —              |
| description      | VARCHAR         | 255                | Yes      | NULL    | —           | —              |
| category_id      | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —              |
| image            | VARCHAR         | 255                | Yes      | NULL    | —           | —              |
| link             | VARCHAR         | 255                | Yes      | NULL    | —           | —              |
| zoom_link        | VARCHAR         | 255                | Yes      | NULL    | —           | —              |
| start_time       | DATETIME        | —                  | Yes      | NULL    | —           | —              |
| start_time_hijri | VARCHAR         | 255                | Yes      | NULL    | —           | —              |
| duration         | VARCHAR         | 255                | Yes      | NULL    | —           | —              |
| meta_title       | VARCHAR         | 255                | Yes      | NULL    | —           | —              |
| meta_description | VARCHAR         | 255                | Yes      | NULL    | —           | —              |
| meeting_id       | VARCHAR         | 255                | Yes      | NULL    | —           | Added 2023-02  |
| passcode         | VARCHAR         | 255                | Yes      | NULL    | —           | Added 2023-02  |
| deleted_at       | TIMESTAMP       | —                  | Yes      | NULL    | —           | Soft delete    |
| created_at       | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| updated_at       | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |

### Foreign Keys

| Column      | References    | On Delete | On Update |
| ----------- | ------------- | --------- | --------- |
| category_id | categories.id | CASCADE   | —         |

### Indexes

| Index              | Columns | Type   |
| ------------------ | ------- | ------ |
| events_slug_unique | slug    | UNIQUE |

### Eloquent Relationships

| Model | Relationship | Related Model | Foreign/Pivot Key |
| ----- | ------------ | ------------- | ----------------- |
| Event | belongsTo    | Category      | category_id       |

### Source

* `database/migrations/2022_03_18_053803_create_events_table.php`
* `database/migrations/2023_02_11_142837_add_culomn_to_events.php` (adds `meeting_id`, `passcode`)
* `app/Models/Event.php`

---

## Table: `ratings`

### Columns

| Column     | Type            | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ---------- | --------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id         | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| name       | VARCHAR         | 255                | No       | —       | —           | —              |
| image      | VARCHAR         | 255                | No       | —       | —           | —              |
| rate       | VARCHAR         | 255                | No       | —       | —           | —              |
| cert_image | VARCHAR         | 255                | No       | —       | —           | —              |
| course_id  | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —              |
| deleted_at | TIMESTAMP       | —                  | Yes      | NULL    | —           | Soft delete    |
| created_at | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| updated_at | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |

### Foreign Keys

| Column    | References | On Delete | On Update |
| --------- | ---------- | --------- | --------- |
| course_id | courses.id | CASCADE   | —         |

### Eloquent Relationships

| Model  | Relationship | Related Model | Foreign/Pivot Key |
| ------ | ------------ | ------------- | ----------------- |
| Rating | belongsTo    | Course        | course_id         |

### Source

* `database/migrations/2022_04_06_024958_create_ratings_table.php`
* `app/Models/Rating.php`

---

## Table: `social_providers`

### Columns

| Column           | Type            | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ---------------- | --------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id               | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| user_id          | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —              |
| provider_user_id | VARCHAR         | 255                | No       | —       | —           | —              |
| provider         | VARCHAR         | 255                | No       | —       | —           | —              |
| created_at       | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| updated_at       | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |

### Foreign Keys

| Column  | References | On Delete | On Update |
| ------- | ---------- | --------- | --------- |
| user_id | users.id   | CASCADE   | —         |

### Eloquent Relationships

| Model          | Relationship | Related Model | Foreign/Pivot Key |
| -------------- | ------------ | ------------- | ----------------- |
| SocialProvider | belongsTo    | User          | user_id           |

### Source

* `database/migrations/2022_04_06_214228_create_social_providers_table.php`
* `app/Models/SocialProvider.php`

---

## Table: `orders`

### Columns

| Column           | Type            | Length / Precision | Nullable | Default | Key / Index | Extra                     |
| ---------------- | --------------- | ------------------ | -------- | ------- | ----------- | ------------------------- |
| id               | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT            |
| uuid             | CHAR            | 36                 | No       | —       | —           | Laravel `uuid()` → CHAR(36); no unique index |
| user_id          | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —                         |
| status           | VARCHAR         | 255                | No       | —       | —           | App-level: pending/accepted/archived/canceled/rejected (not a DB enum) |
| amount           | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| currency         | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| pay_image        | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| transaction_id   | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| transaction_date | DATETIME        | —                  | Yes      | NULL    | —           | —                         |
| response_code    | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| response_message | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| customer_name    | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| customer_email   | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| customer_phone   | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| card_type        | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| card_brand       | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| card_number      | VARCHAR         | 255                | Yes      | NULL    | —           | —                         |
| signature        | VARCHAR         | 255                | Yes      | NULL    | —           | Also used to store coupon code (see Coupon::orders()) |
| bank_code        | TEXT            | —                  | Yes      | NULL    | —           | Added 2022-11             |
| deleted_at       | TIMESTAMP       | —                  | Yes      | NULL    | —           | Soft delete               |
| created_at       | TIMESTAMP       | —                  | Yes      | NULL    | —           | —                         |
| updated_at       | TIMESTAMP       | —                  | Yes      | NULL    | —           | —                         |

### Foreign Keys

| Column  | References | On Delete | On Update |
| ------- | ---------- | --------- | --------- |
| user_id | users.id   | CASCADE   | —         |

### Eloquent Relationships

| Model | Relationship  | Related Model | Foreign/Pivot Key                              |
| ----- | ------------- | ------------- | ---------------------------------------------- |
| Order | belongsTo     | User          | user_id                                        |
| Order | belongsToMany | Course (items)| `course_order` (order_id / course_id), withPivot `expiry_date` |
| Order | belongsToMany | Book (bookItems) | `book_order` (order_id / book_id)           |

### Source

* `database/migrations/2022_04_06_222616_create_orders_table.php`
* `database/migrations/2022_11_21_154632_add_bank_code_to_items.php` (adds `bank_code` to `orders` despite the filename)
* `app/Models/Order.php`

---

## Table: `course_order` (pivot)

### Columns

| Column      | Type            | Length / Precision | Nullable | Default | Key / Index | Extra         |
| ----------- | --------------- | ------------------ | -------- | ------- | ----------- | ------------- |
| course_id   | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —             |
| order_id    | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —             |
| expiry_date | DATE            | —                  | Yes      | NULL    | —           | Added 2023-12 |

No primary key, no timestamps.

### Foreign Keys

| Column    | References | On Delete | On Update |
| --------- | ---------- | --------- | --------- |
| course_id | courses.id | CASCADE   | —         |
| order_id  | orders.id  | CASCADE   | —         |

### Eloquent Relationships

| Model  | Relationship  | Related Model | Pivot Keys              |
| ------ | ------------- | ------------- | ----------------------- |
| Order  | belongsToMany | Course        | order_id / course_id    |
| Course | belongsToMany | Order         | course_id / order_id    |

### Source

* `database/migrations/2022_04_06_223005_create_course_order_table.php`
* `database/migrations/2023_12_27_003729_add_expiry_date_to_course_order_table.php`

---

## Table: `coupons`

### Columns

| Column           | Type            | Length / Precision                    | Nullable | Default   | Key / Index | Extra                       |
| ---------------- | --------------- | ------------------------------------- | -------- | --------- | ----------- | --------------------------- |
| id               | BIGINT UNSIGNED | —                                     | No       | —         | PRIMARY     | AUTO_INCREMENT              |
| name             | VARCHAR         | 255                                   | No       | —         | —           | —                           |
| description      | VARCHAR         | 255                                   | Yes      | NULL      | —           | —                           |
| code             | VARCHAR         | 255                                   | No       | —         | UNIQUE      | —                           |
| amount           | INT             | —                                     | No       | —         | —           | —                           |
| start_date       | DATE            | —                                     | No       | —         | —           | —                           |
| end_date         | DATE            | —                                     | No       | —         | —           | —                           |
| type             | ENUM            | ('generic','category','course','user')| No       | 'generic' | —           | —                           |
| discount_type    | ENUM            | ('percent','fixed')                   | No       | 'fixed'   | —           | —                           |
| subscribed       | TINYINT(1)      | —                                     | No       | 0         | —           | Added 2024-01, after discount_type |
| status           | ENUM            | ('active','inactive')                 | No       | —         | —           | No default                  |
| usage_per_coupon | INT             | —                                     | Yes      | NULL      | —           | —                           |
| usage_per_user   | INT             | —                                     | Yes      | NULL      | —           | —                           |
| deleted_at       | TIMESTAMP       | —                                     | Yes      | NULL      | —           | Soft delete                 |
| created_at       | TIMESTAMP       | —                                     | Yes      | NULL      | —           | —                           |
| updated_at       | TIMESTAMP       | —                                     | Yes      | NULL      | —           | —                           |

### Foreign Keys

None (DB level).

### Indexes

| Index               | Columns | Type   |
| ------------------- | ------- | ------ |
| coupons_code_unique | code    | UNIQUE |

### Eloquent Relationships

| Model  | Relationship  | Related Model | Foreign/Pivot Key                                        |
| ------ | ------------- | ------------- | -------------------------------------------------------- |
| Coupon | belongsToMany | Course        | `coupon_course` (default keys coupon_id / course_id)     |
| Coupon | hasMany       | Order         | `orders.signature` ↔ `coupons.code` (non-key columns, no DB FK) |

### Source

* `database/migrations/2022_04_07_164126_create_coupons_table.php`
* `database/migrations/2024_01_25_213703_add_subscribed_to_coupons_table.php`
* `app/Models/Coupon.php`

---

## Table: `results`

### Columns

| Column       | Type            | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ------------ | --------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id           | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| total_points | INT             | —                  | Yes      | NULL    | —           | —              |
| user_id      | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —              |
| quiz_id      | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —              |
| created_at   | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| updated_at   | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| deleted_at   | TIMESTAMP       | —                  | Yes      | NULL    | —           | Soft delete    |

### Foreign Keys

| Column  | References | On Delete | On Update |
| ------- | ---------- | --------- | --------- |
| user_id | users.id   | CASCADE   | —         |
| quiz_id | quizzes.id | CASCADE   | —         |

### Eloquent Relationships

| Model  | Relationship  | Related Model | Foreign/Pivot Key                                         |
| ------ | ------------- | ------------- | --------------------------------------------------------- |
| Result | belongsTo     | User          | user_id                                                   |
| Result | belongsTo     | Quiz          | quiz_id                                                   |
| Result | belongsToMany | Question      | `question_result` (result_id / question_id), withPivot question_id, option_id, points |

### Source

* `database/migrations/2022_05_05_210319_create_results_table.php`
* `app/Models/Result.php` (explicit `public $table = 'results'`)

---

## Table: `question_result` (pivot with own PK)

### Columns

| Column      | Type            | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ----------- | --------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id          | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| result_id   | BIGINT UNSIGNED | —                  | No       | —       | INDEX (FK)  | —              |
| question_id | BIGINT UNSIGNED | —                  | No       | —       | INDEX (FK)  | —              |
| option_id   | BIGINT UNSIGNED | —                  | No       | —       | INDEX (FK)  | —              |
| points      | INT             | —                  | No       | 0       | —           | —              |
| created_at  | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| updated_at  | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |

### Foreign Keys

| Column      | References   | On Delete | On Update |
| ----------- | ------------ | --------- | --------- |
| result_id   | results.id   | CASCADE   | —         |
| question_id | questions.id | CASCADE   | —         |
| option_id   | options.id   | CASCADE   | —         |

### Source

* `database/migrations/2022_05_05_211034_create_question_result_pivot_table.php` (creates `question_result`; note the `down()` drops the non-existent `question_result_pivot`)

---

## Table: `settings`

### Columns

| Column     | Type            | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ---------- | --------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id         | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| name       | VARCHAR         | 255                | No       | —       | —           | —              |
| key        | VARCHAR         | 255                | No       | —       | UNIQUE      | —              |
| type       | VARCHAR         | 255                | No       | —       | —           | —              |
| value      | LONGTEXT        | —                  | Yes      | NULL    | —           | —              |
| created_at | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| updated_at | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |

### Indexes

| Index              | Columns | Type   |
| ------------------ | ------- | ------ |
| settings_key_unique | key    | UNIQUE |

### Source

* `database/migrations/2022_08_11_210128_create_settings_table.php`
* `app/Models/Setting.php`

---

## Table: `apple_products`

### Columns

| Column     | Type            | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ---------- | --------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id         | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| price      | VARCHAR         | 255                | No       | —       | —           | —              |
| product_id | VARCHAR         | 255                | No       | —       | —           | —              |
| created_at | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| updated_at | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| deleted_at | TIMESTAMP       | —                  | Yes      | NULL    | —           | Soft delete    |

### Source

* `database/migrations/2022_12_10_204350_create_apple_products_table.php`
* `app/Models/AppleProduct.php`

---

## Table: `paymob_logs`

### Columns

| Column     | Type            | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ---------- | --------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id         | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| content    | TEXT            | —                  | No       | —       | —           | —              |
| created_at | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| updated_at | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |

### Source

* `database/migrations/2023_01_16_182719_create_paymob_logs_table.php`
* `app/Models/PaymobLog.php`

---

## Table: `audits` (owen-it/laravel-auditing)

Created on the default connection (`config('audit.drivers.database.connection')` → default), table name from `config('audit.drivers.database.table')` = `audits`, morph prefix `user`.

### Columns

| Column         | Type            | Length / Precision | Nullable | Default | Key / Index       | Extra          |
| -------------- | --------------- | ------------------ | -------- | ------- | ----------------- | -------------- |
| id             | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY           | AUTO_INCREMENT |
| user_type      | VARCHAR         | 255                | Yes      | NULL    | INDEX (composite) | —              |
| user_id        | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (composite) | —              |
| event          | VARCHAR         | 255                | No       | —       | —                 | —              |
| auditable_type | VARCHAR         | 255                | No       | —       | INDEX (composite) | morphs()       |
| auditable_id   | BIGINT UNSIGNED | —                  | No       | —       | INDEX (composite) | morphs()       |
| old_values     | TEXT            | —                  | Yes      | NULL    | —                 | —              |
| new_values     | TEXT            | —                  | Yes      | NULL    | —                 | —              |
| url            | TEXT            | —                  | Yes      | NULL    | —                 | —              |
| ip_address     | VARCHAR         | 45                 | Yes      | NULL    | —                 | ipAddress()    |
| user_agent     | VARCHAR         | 1023               | Yes      | NULL    | —                 | —              |
| tags           | VARCHAR         | 255                | Yes      | NULL    | —                 | —              |
| created_at     | TIMESTAMP       | —                  | Yes      | NULL    | —                 | —              |
| updated_at     | TIMESTAMP       | —                  | Yes      | NULL    | —                 | —              |

### Indexes

| Index                      | Columns                        | Type  |
| -------------------------- | ------------------------------ | ----- |
| audits_user_id_user_type_index | user_id, user_type         | INDEX |
| audits_auditable_type_auditable_id_index | auditable_type, auditable_id | INDEX |

### Source

* `database/migrations/2023_07_15_201017_create_audits_table.php`
* `config/audit.php`

---

## Table: `book_order` (pivot)

### Columns

| Column   | Type            | Length / Precision | Nullable | Default | Key / Index | Extra |
| -------- | --------------- | ------------------ | -------- | ------- | ----------- | ----- |
| book_id  | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —     |
| order_id | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —     |

No primary key, no timestamps.

### Foreign Keys

| Column   | References | On Delete | On Update |
| -------- | ---------- | --------- | --------- |
| book_id  | books.id   | CASCADE   | —         |
| order_id | orders.id  | CASCADE   | —         |

### Eloquent Relationships

| Model | Relationship  | Related Model | Pivot Keys          |
| ----- | ------------- | ------------- | ------------------- |
| Book  | belongsToMany | Order         | book_id / order_id  |
| Order | belongsToMany | Book          | order_id / book_id  |

### Source

* `database/migrations/2023_08_05_180315_create_book_order_table.php`

---

## Table: `coupon_course` (pivot)

### Columns

| Column    | Type            | Length / Precision | Nullable | Default | Key / Index | Extra |
| --------- | --------------- | ------------------ | -------- | ------- | ----------- | ----- |
| coupon_id | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —     |
| course_id | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —     |

No primary key, no timestamps.

### Foreign Keys

| Column    | References | On Delete | On Update |
| --------- | ---------- | --------- | --------- |
| coupon_id | coupons.id | CASCADE   | —         |
| course_id | courses.id | CASCADE   | —         |

### Eloquent Relationships

| Model  | Relationship  | Related Model | Pivot Keys            |
| ------ | ------------- | ------------- | --------------------- |
| Coupon | belongsToMany | Course        | coupon_id / course_id |
| Course | belongsToMany | Coupon        | course_id / coupon_id |

### Source

* `database/migrations/2023_09_11_023253_create_coupon_course_table.php`

---

## Table: `certificates`

### Columns

| Column       | Type            | Length / Precision | Nullable | Default    | Key / Index | Extra                                  |
| ------------ | --------------- | ------------------ | -------- | ---------- | ----------- | -------------------------------------- |
| id           | BIGINT UNSIGNED | —                  | No       | —          | PRIMARY     | AUTO_INCREMENT                         |
| name         | VARCHAR         | 255                | No       | —          | —           | —                                      |
| email        | VARCHAR         | 255                | No       | —          | —           | —                                      |
| phone        | VARCHAR         | 255                | No       | —          | —           | —                                      |
| id_number    | VARCHAR         | 255                | No       | —          | —           | —                                      |
| degree       | VARCHAR         | 255                | No       | —          | —           | —                                      |
| nationality  | VARCHAR         | 255                | No       | 'سعودي'    | —           | Arabic default value                   |
| start_date   | VARCHAR         | 255                | Yes      | NULL       | —           | Added 2023-12 (Hijri, stored as string), after nationality |
| end_date     | VARCHAR         | 255                | Yes      | NULL       | —           | Added 2023-12                          |
| start_date_g | VARCHAR         | 255                | Yes      | NULL       | —           | Added 2026-01 (Gregorian), after end_date |
| end_date_g   | VARCHAR         | 255                | Yes      | NULL       | —           | Added 2026-01, after start_date_g      |
| amount       | INT             | —                  | Yes      | NULL       | —           | —                                      |
| pay_image    | VARCHAR         | 255                | Yes      | NULL       | —           | —                                      |
| cert_file    | VARCHAR         | 255                | Yes      | NULL       | —           | —                                      |
| cert_status  | VARCHAR         | 255                | No       | 'received' | —           | App-level: received/processing/issued  |
| user_id      | BIGINT UNSIGNED | —                  | Yes      | NULL       | INDEX (FK)  | —                                      |
| category_id  | BIGINT UNSIGNED | —                  | Yes      | NULL       | INDEX (FK)  | —                                      |
| deleted_at   | TIMESTAMP       | —                  | Yes      | NULL       | —           | Soft delete                            |
| created_at   | TIMESTAMP       | —                  | Yes      | NULL       | —           | —                                      |
| updated_at   | TIMESTAMP       | —                  | Yes      | NULL       | —           | —                                      |

### Foreign Keys

| Column      | References    | On Delete | On Update |
| ----------- | ------------- | --------- | --------- |
| user_id     | users.id      | CASCADE   | —         |
| category_id | categories.id | CASCADE   | —         |

### Eloquent Relationships

| Model       | Relationship | Related Model | Foreign/Pivot Key |
| ----------- | ------------ | ------------- | ----------------- |
| Certificate | belongsTo    | User          | user_id           |
| Certificate | belongsTo    | Category      | category_id       |

### Source

* `database/migrations/2023_09_23_172629_create_certificates_table.php`
* `database/migrations/2023_12_25_032204_add_date_to_certificates_table.php`
* `database/migrations/2026_01_08_214825_add_gregorian_dates_to_certificates_table.php`
* `app/Models/Certificate.php`

---

## Table: `complaints`

### Columns

| Column       | Type            | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ------------ | --------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id           | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| user_id      | BIGINT UNSIGNED | —                  | No       | —       | INDEX (FK)  | —              |
| subject      | VARCHAR         | 255                | No       | —       | —           | —              |
| payment_type | VARCHAR         | 50                 | No       | —       | —           | —              |
| status       | VARCHAR         | 50                 | No       | —       | —           | —              |
| created_by   | VARCHAR         | 255                | No       | —       | —           | No DB FK       |
| deleted_at   | TIMESTAMP       | —                  | Yes      | NULL    | —           | Soft delete    |
| created_at   | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| updated_at   | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |

### Foreign Keys

| Column  | References | On Delete | On Update |
| ------- | ---------- | --------- | --------- |
| user_id | users.id   | CASCADE   | —         |

### Eloquent Relationships

| Model     | Relationship | Related Model       | Foreign/Pivot Key                 |
| --------- | ------------ | ------------------- | --------------------------------- |
| Complaint | belongsTo    | User                | user_id                           |
| Complaint | hasMany      | ComplaintResponses  | complaint_responses.complaint_id  |

### Source

* `database/migrations/2024_07_11_140503_create_complaints_table.php`
* `app/Models/Complaint.php`

---

## Table: `complaint_responses`

### Columns

| Column       | Type            | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ------------ | --------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id           | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| complaint_id | BIGINT UNSIGNED | —                  | No       | —       | INDEX (FK)  | —              |
| responder_id | BIGINT UNSIGNED | —                  | No       | —       | INDEX (FK)  | —              |
| description  | LONGTEXT        | —                  | No       | —       | —           | —              |
| deleted_at   | TIMESTAMP       | —                  | Yes      | NULL    | —           | Soft delete    |
| created_at   | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| updated_at   | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |

### Foreign Keys

| Column       | References    | On Delete | On Update |
| ------------ | ------------- | --------- | --------- |
| complaint_id | complaints.id | CASCADE   | —         |
| responder_id | users.id      | CASCADE   | —         |

### Eloquent Relationships

| Model              | Relationship | Related Model | Foreign/Pivot Key |
| ------------------ | ------------ | ------------- | ----------------- |
| ComplaintResponses | belongsTo    | Complaint     | complaint_id      |
| ComplaintResponses | belongsTo    | User (responder) | responder_id   |

### Source

* `database/migrations/2024_07_11_140525_create_complaint_responses_table.php`
* `app/Models/ComplaintResponses.php`

---

## Table: `course_requests`

### Columns

| Column        | Type            | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ------------- | --------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id            | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| reference     | VARCHAR         | 255                | No       | —       | —           | —              |
| name          | VARCHAR         | 255                | No       | —       | —           | —              |
| email         | VARCHAR         | 255                | No       | —       | —           | —              |
| phone         | VARCHAR         | 255                | No       | —       | —           | —              |
| exam_date     | DATE            | —                  | Yes      | NULL    | —           | —              |
| is_subscribed | TINYINT(1)      | —                  | No       | 0       | —           | —              |
| user_id       | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —              |
| category_id   | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —              |
| course_id     | BIGINT UNSIGNED | —                  | Yes      | NULL    | INDEX (FK)  | —              |
| deleted_at    | TIMESTAMP       | —                  | Yes      | NULL    | —           | Soft delete    |
| created_at    | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |
| updated_at    | TIMESTAMP       | —                  | Yes      | NULL    | —           | —              |

### Foreign Keys

| Column      | References    | On Delete | On Update |
| ----------- | ------------- | --------- | --------- |
| user_id     | users.id      | CASCADE   | —         |
| category_id | categories.id | CASCADE   | —         |
| course_id   | courses.id    | CASCADE   | —         |

### Eloquent Relationships

| Model         | Relationship | Related Model | Foreign/Pivot Key |
| ------------- | ------------ | ------------- | ----------------- |
| CourseRequest | belongsTo    | User          | user_id           |
| CourseRequest | belongsTo    | Category      | category_id       |
| CourseRequest | belongsTo    | Course        | course_id         |

### Source

* `database/migrations/2025_01_06_043314_create_course_requests_table.php`
* `app/Models/CourseRequest.php`

---

## Table: `jobs` (queue)

### Columns

| Column       | Type                | Length / Precision | Nullable | Default | Key / Index | Extra          |
| ------------ | ------------------- | ------------------ | -------- | ------- | ----------- | -------------- |
| id           | BIGINT UNSIGNED     | —                  | No       | —       | PRIMARY     | AUTO_INCREMENT |
| queue        | VARCHAR             | 255                | No       | —       | INDEX       | —              |
| payload      | LONGTEXT            | —                  | No       | —       | —           | —              |
| attempts     | TINYINT UNSIGNED    | —                  | No       | —       | —           | —              |
| reserved_at  | INT UNSIGNED        | —                  | Yes      | NULL    | —           | —              |
| available_at | INT UNSIGNED        | —                  | No       | —       | —           | —              |
| created_at   | INT UNSIGNED        | —                  | No       | —       | —           | Unix timestamp, not TIMESTAMP |

### Indexes

| Index             | Columns | Type  |
| ----------------- | ------- | ----- |
| jobs_queue_index  | queue   | INDEX |

### Source

* `database/migrations/2025_03_05_045325_create_jobs_table.php`
* `config/queue.php` (`database` queue driver → table `jobs`)

---

## Table: `file_transfers`

### Columns

| Column        | Type            | Length / Precision                     | Nullable | Default   | Key / Index       | Extra          |
| ------------- | --------------- | -------------------------------------- | -------- | --------- | ----------------- | -------------- |
| id            | BIGINT UNSIGNED | —                                      | No       | —         | PRIMARY           | AUTO_INCREMENT |
| batch_id      | VARCHAR         | 255                                    | No       | —         | INDEX             | —              |
| file_path     | TEXT            | —                                      | No       | —         | —                 | —              |
| status        | ENUM            | ('pending','processing','completed','failed') | No | 'pending' | INDEX (composite) | —           |
| error_message | TEXT            | —                                      | Yes      | NULL      | —                 | —              |
| file_size     | BIGINT          | —                                      | Yes      | NULL      | —                 | Signed BIGINT  |
| completed_at  | TIMESTAMP       | —                                      | Yes      | NULL      | —                 | —              |
| created_at    | TIMESTAMP       | —                                      | Yes      | NULL      | —                 | —              |
| updated_at    | TIMESTAMP       | —                                      | Yes      | NULL      | —                 | —              |

### Indexes

| Index                          | Columns           | Type  |
| ------------------------------ | ----------------- | ----- |
| file_transfers_batch_id_index  | batch_id          | INDEX |
| file_transfers_batch_id_status_index | batch_id, status | INDEX |

### Source

* `database/migrations/2026_01_07_160820_create_file_transfers_table.php`
* `app/Models/FileTransfer.php`

---

## Table: `bunny_drive_exports`

### Columns

| Column         | Type            | Length / Precision                     | Nullable | Default   | Key / Index       | Extra          |
| -------------- | --------------- | -------------------------------------- | -------- | --------- | ----------------- | -------------- |
| id             | BIGINT UNSIGNED | —                                      | No       | —         | PRIMARY           | AUTO_INCREMENT |
| batch_id       | VARCHAR         | 255                                    | No       | —         | INDEX (composite) | —              |
| meeting_id     | VARCHAR         | 255                                    | Yes      | NULL      | INDEX             | —              |
| lecture_id     | BIGINT UNSIGNED | —                                      | Yes      | NULL      | INDEX (FK)        | —              |
| course_id      | BIGINT UNSIGNED | —                                      | Yes      | NULL      | INDEX (FK)        | —              |
| bunny_id       | VARCHAR         | 255                                    | Yes      | NULL      | —                 | —              |
| status         | ENUM            | ('pending','processing','completed','failed') | No | 'pending' | INDEX (composite) | —           |
| error_message  | TEXT            | —                                      | Yes      | NULL      | —                 | —              |
| drive_file_id  | VARCHAR         | 255                                    | Yes      | NULL      | —                 | —              |
| drive_file_url | TEXT            | —                                      | Yes      | NULL      | —                 | —              |
| drive_path     | VARCHAR         | 255                                    | Yes      | NULL      | —                 | —              |
| file_size      | BIGINT          | —                                      | Yes      | NULL      | —                 | —              |
| completed_at   | TIMESTAMP       | —                                      | Yes      | NULL      | —                 | —              |
| created_at     | TIMESTAMP       | —                                      | Yes      | NULL      | —                 | —              |
| updated_at     | TIMESTAMP       | —                                      | Yes      | NULL      | —                 | —              |

### Foreign Keys

| Column     | References  | On Delete | On Update |
| ---------- | ----------- | --------- | --------- |
| lecture_id | lectures.id | SET NULL  | —         |
| course_id  | courses.id  | SET NULL  | —         |

### Indexes

| Index                                  | Columns          | Type  |
| -------------------------------------- | ---------------- | ----- |
| bunny_drive_exports_batch_id_status_index | batch_id, status | INDEX |
| bunny_drive_exports_meeting_id_index   | meeting_id       | INDEX |

### Eloquent Relationships

| Model            | Relationship | Related Model | Foreign/Pivot Key |
| ---------------- | ------------ | ------------- | ----------------- |
| BunnyDriveExport | belongsTo    | Lecture       | lecture_id        |
| BunnyDriveExport | belongsTo    | Course        | course_id         |

### Source

* `database/migrations/2026_04_29_000001_create_bunny_drive_exports_table.php`
* `app/Models/BunnyDriveExport.php`

---

## Table: `bunny_video_deletes`

### Columns

| Column        | Type            | Length / Precision                     | Nullable | Default   | Key / Index       | Extra          |
| ------------- | --------------- | -------------------------------------- | -------- | --------- | ----------------- | -------------- |
| id            | BIGINT UNSIGNED | —                                      | No       | —         | PRIMARY           | AUTO_INCREMENT |
| batch_id      | VARCHAR         | 255                                    | No       | —         | INDEX (composite) | —              |
| bunny_id      | VARCHAR         | 255                                    | No       | —         | INDEX             | —              |
| status        | ENUM            | ('pending','processing','completed','failed') | No | 'pending' | INDEX (composite) | —           |
| error_message | TEXT            | —                                      | Yes      | NULL      | —                 | —              |
| http_status   | INT             | —                                      | Yes      | NULL      | —                 | —              |
| completed_at  | TIMESTAMP       | —                                      | Yes      | NULL      | —                 | —              |
| created_at    | TIMESTAMP       | —                                      | Yes      | NULL      | —                 | —              |
| updated_at    | TIMESTAMP       | —                                      | Yes      | NULL      | —                 | —              |

### Indexes

| Index                                  | Columns          | Type  |
| -------------------------------------- | ---------------- | ----- |
| bunny_video_deletes_batch_id_status_index | batch_id, status | INDEX |
| bunny_video_deletes_bunny_id_index     | bunny_id         | INDEX |

### Source

* `database/migrations/2026_05_06_000001_create_bunny_video_deletes_table.php`
* `app/Models/BunnyVideoDelete.php`

---

## Table: `file_transfer_jobs`

### Columns

| Column            | Type            | Length / Precision                                | Nullable | Default    | Key / Index       | Extra                                |
| ----------------- | --------------- | ------------------------------------------------- | -------- | ---------- | ----------------- | ------------------------------------ |
| id                | BIGINT UNSIGNED | —                                                 | No       | —          | PRIMARY           | AUTO_INCREMENT                       |
| batch_id          | VARCHAR         | 255                                               | No       | —          | INDEX             | —                                    |
| operation         | ENUM            | ('transfer','delete')                             | No       | 'transfer' | —                 | —                                    |
| source_provider   | ENUM            | ('bunny','drive','spaces','youtube')              | Yes      | NULL       | —                 | 'youtube' added 2026-08 via raw ALTER |
| source_identifier | TEXT            | —                                                 | No       | —          | —                 | —                                    |
| target_provider   | ENUM            | ('bunny','drive','spaces','youtube')              | Yes      | NULL       | —                 | 'youtube' added 2026-08 via raw ALTER |
| target_path       | TEXT            | —                                                 | Yes      | NULL       | —                 | —                                    |
| target_identifier | VARCHAR         | 255                                               | Yes      | NULL       | —                 | —                                    |
| target_url        | TEXT            | —                                                 | Yes      | NULL       | —                 | —                                    |
| status            | ENUM            | ('pending','downloading','uploading','completed','failed') | No | 'pending' | INDEX (composite) | —                              |
| error_message     | TEXT            | —                                                 | Yes      | NULL       | —                 | —                                    |
| http_status       | INT             | —                                                 | Yes      | NULL       | —                 | —                                    |
| file_size         | BIGINT          | —                                                 | Yes      | NULL       | —                 | —                                    |
| lecture_id        | BIGINT UNSIGNED | —                                                 | Yes      | NULL       | INDEX (FK)        | —                                    |
| course_id         | BIGINT UNSIGNED | —                                                 | Yes      | NULL       | INDEX (FK)        | —                                    |
| meeting_id        | VARCHAR         | 255                                               | Yes      | NULL       | INDEX             | —                                    |
| metadata          | JSON            | —                                                 | Yes      | NULL       | —                 | —                                    |
| completed_at      | TIMESTAMP       | —                                                 | Yes      | NULL       | —                 | —                                    |
| created_at        | TIMESTAMP       | —                                                 | Yes      | NULL       | —                 | —                                    |
| updated_at        | TIMESTAMP       | —                                                 | Yes      | NULL       | —                 | —                                    |

### Foreign Keys

| Column     | References  | On Delete | On Update |
| ---------- | ----------- | --------- | --------- |
| lecture_id | lectures.id | SET NULL  | —         |
| course_id  | courses.id  | SET NULL  | —         |

### Indexes

| Index                                   | Columns          | Type  |
| --------------------------------------- | ---------------- | ----- |
| file_transfer_jobs_batch_id_status_index | batch_id, status | INDEX |
| file_transfer_jobs_meeting_id_index     | meeting_id       | INDEX |
| file_transfer_jobs_batch_id_index       | batch_id         | INDEX |

### Eloquent Relationships

| Model           | Relationship | Related Model | Foreign/Pivot Key        |
| --------------- | ------------ | ------------- | ------------------------ |
| FileTransferJob | belongsTo    | Lecture       | lecture_id (withTrashed) |
| FileTransferJob | belongsTo    | Course        | course_id (withTrashed)  |

Model casts `operation` / `source_provider` / `target_provider` / `status` to PHP backed enums in `app/Domain/FileTransfer/Enums/`.

### Source

* `database/migrations/2026_06_06_000001_create_file_transfer_jobs_table.php`
* `database/migrations/2026_08_09_000001_add_youtube_to_file_transfer_jobs_providers.php` (raw `ALTER TABLE ... MODIFY COLUMN` adds `'youtube'` to both provider ENUMs)
* `app/Models/FileTransferJob.php`

---

## Table: `google_oauth_tokens`

Created as `youtube_tokens` (2026-08-09), then renamed and restructured by `2026_08_11_000001_generalize_youtube_tokens_to_google_oauth_tokens.php`. The final schema below applies the rename + column changes (the migration avoids `renameColumn` because doctrine/dbal is not installed).

### Columns (final)

| Column        | Type            | Length / Precision | Nullable | Default   | Key / Index | Extra                            |
| ------------- | --------------- | ------------------ | -------- | --------- | ----------- | -------------------------------- |
| id            | BIGINT UNSIGNED | —                  | No       | —         | PRIMARY     | AUTO_INCREMENT                   |
| purpose       | VARCHAR         | 255                | No       | 'youtube' | UNIQUE      | Added 2026-08-11; one row per purpose ('youtube', 'drive') |
| access_token  | TEXT            | —                  | No       | —         | —           | Eloquent `encrypted` cast        |
| refresh_token | TEXT            | —                  | No       | —         | —           | Eloquent `encrypted` cast        |
| token_type    | VARCHAR         | 255                | No       | 'Bearer'  | —           | —                                |
| scopes        | TEXT            | —                  | Yes      | NULL      | —           | —                                |
| expires_at    | TIMESTAMP       | —                  | Yes      | NULL      | —           | —                                |
| account_email | VARCHAR         | 255                | Yes      | NULL      | —           | Added 2026-08-11, after expires_at |
| account_label | VARCHAR         | 255                | Yes      | NULL      | —           | Added 2026-08-11, after account_email |
| created_at    | TIMESTAMP       | —                  | Yes      | NULL      | —           | —                                |
| updated_at    | TIMESTAMP       | —                  | Yes      | NULL      | —           | —                                |

Dropped during generalization: `account` (was VARCHAR UNIQUE DEFAULT 'default'), `channel_title` (values copied to `account_label`).

### Indexes

| Index                              | Columns | Type   |
| ---------------------------------- | ------- | ------ |
| google_oauth_tokens_purpose_unique | purpose | UNIQUE |

### Source

* `database/migrations/2026_08_09_000002_create_youtube_tokens_table.php`
* `database/migrations/2026_08_11_000001_generalize_youtube_tokens_to_google_oauth_tokens.php`
* `app/Models/GoogleOAuthToken.php` (explicit `protected $table = 'google_oauth_tokens'`)

---

## Table: `telescope_entries` (package: laravel/telescope)

Created by the vendored migration that `TelescopeServiceProvider` auto-loads (unless `Telescope::ignoreMigrations()` is called — it is not in this repo). Connection = `config('telescope.storage.database.connection')` → default mysql. Disabled during tests (`TELESCOPE_ENABLED=false` in `phpunit.xml`).

### Columns

| Column                  | Type            | Length / Precision | Nullable | Default | Key / Index       | Extra          |
| ----------------------- | --------------- | ------------------ | -------- | ------- | ----------------- | -------------- |
| sequence                | BIGINT UNSIGNED | —                  | No       | —       | PRIMARY           | AUTO_INCREMENT |
| uuid                    | CHAR            | 36                 | No       | —       | UNIQUE            | —              |
| batch_id                | CHAR            | 36                 | No       | —       | INDEX             | —              |
| family_hash             | VARCHAR         | 255                | Yes      | NULL    | INDEX             | —              |
| should_display_on_index | TINYINT(1)      | —                  | No       | 1       | INDEX (composite) | —              |
| type                    | VARCHAR         | 20                 | No       | —       | INDEX (composite) | —              |
| content                 | LONGTEXT        | —                  | No       | —       | —                 | —              |
| created_at              | DATETIME        | —                  | Yes      | NULL    | INDEX             | —              |

### Indexes

| Index                                     | Columns                       | Type   |
| ----------------------------------------- | ----------------------------- | ------ |
| telescope_entries_uuid_unique             | uuid                          | UNIQUE |
| telescope_entries_batch_id_index          | batch_id                      | INDEX  |
| telescope_entries_family_hash_index       | family_hash                   | INDEX  |
| telescope_entries_created_at_index        | created_at                    | INDEX  |
| telescope_entries_type_should_display_*   | type, should_display_on_index | INDEX  |

### Source

* `vendor/laravel/telescope/database/migrations/2018_08_08_100000_create_telescope_entries_table.php` (auto-loaded)
* `config/telescope.php`

---

## Table: `telescope_entries_tags` (package: laravel/telescope)

### Columns

| Column     | Type    | Length / Precision | Nullable | Default | Key / Index         | Extra |
| ---------- | ------- | ------------------ | -------- | ------- | ------------------- | ----- |
| entry_uuid | CHAR    | 36                 | No       | —       | PRIMARY (composite) | —     |
| tag        | VARCHAR | 255                | No       | —       | PRIMARY (composite), INDEX | — |

### Foreign Keys

| Column     | References             | On Delete | On Update |
| ---------- | ---------------------- | --------- | --------- |
| entry_uuid | telescope_entries.uuid | CASCADE   | —         |

### Source

* `vendor/laravel/telescope/database/migrations/2018_08_08_100000_create_telescope_entries_table.php`

---

## Table: `telescope_monitoring` (package: laravel/telescope)

### Columns

| Column | Type    | Length / Precision | Nullable | Default | Key / Index | Extra |
| ------ | ------- | ------------------ | -------- | ------- | ----------- | ----- |
| tag    | VARCHAR | 255                | No       | —       | PRIMARY     | —     |

### Source

* `vendor/laravel/telescope/database/migrations/2018_08_08_100000_create_telescope_entries_table.php`

---

# Database Relationships

## Confirmed database-level foreign keys

```
zoom_users.user_id -> users.id (ON DELETE CASCADE)
courses.category_id -> categories.id (ON DELETE CASCADE)
chapters.course_id -> courses.id (ON DELETE CASCADE)
lectures.chapter_id -> chapters.id (ON DELETE CASCADE)
books.course_id -> courses.id (ON DELETE CASCADE)
books.category_id -> categories.id (ON DELETE CASCADE)
quizzes.user_id -> users.id (ON DELETE CASCADE)
quizzes.category_id -> categories.id (ON DELETE CASCADE)
quizzes.course_id -> courses.id (ON DELETE CASCADE)
quizzes.lecture_id -> lectures.id (ON DELETE CASCADE)
sections.quiz_id -> quizzes.id (ON DELETE CASCADE)
questions.section_id -> sections.id (ON DELETE CASCADE)
options.question_id -> questions.id (ON DELETE CASCADE)
quiz_files.section_id -> sections.id (ON DELETE CASCADE)
quiz_files.question_id -> questions.id (ON DELETE CASCADE)
events.category_id -> categories.id (ON DELETE CASCADE)
ratings.course_id -> courses.id (ON DELETE CASCADE)
social_providers.user_id -> users.id (ON DELETE CASCADE)
orders.user_id -> users.id (ON DELETE CASCADE)
results.user_id -> users.id (ON DELETE CASCADE)
results.quiz_id -> quizzes.id (ON DELETE CASCADE)
question_result.result_id -> results.id (ON DELETE CASCADE)
question_result.question_id -> questions.id (ON DELETE CASCADE)
question_result.option_id -> options.id (ON DELETE CASCADE)
certificates.user_id -> users.id (ON DELETE CASCADE)
certificates.category_id -> categories.id (ON DELETE CASCADE)
complaints.user_id -> users.id (ON DELETE CASCADE)
complaint_responses.complaint_id -> complaints.id (ON DELETE CASCADE)
complaint_responses.responder_id -> users.id (ON DELETE CASCADE)
course_requests.user_id -> users.id (ON DELETE CASCADE)
course_requests.category_id -> categories.id (ON DELETE CASCADE)
course_requests.course_id -> courses.id (ON DELETE CASCADE)
bunny_drive_exports.lecture_id -> lectures.id (ON DELETE SET NULL)
bunny_drive_exports.course_id -> courses.id (ON DELETE SET NULL)
file_transfer_jobs.lecture_id -> lectures.id (ON DELETE SET NULL)
file_transfer_jobs.course_id -> courses.id (ON DELETE SET NULL)
user_permissions.permission_id -> permissions.id (ON DELETE CASCADE)
user_roles.role_id -> roles.id (ON DELETE CASCADE)
role_permissions.permission_id -> permissions.id (ON DELETE CASCADE)
role_permissions.role_id -> roles.id (ON DELETE CASCADE)
telescope_entries_tags.entry_uuid -> telescope_entries.uuid (ON DELETE CASCADE)  [package]
```

## Pivot tables

`course_user`

* `course_id -> courses.id` (CASCADE)
* `user_id -> users.id` (CASCADE)

`book_course`

* `book_id -> books.id` (CASCADE)
* `course_id -> courses.id` (CASCADE)

`course_order`

* `course_id -> courses.id` (CASCADE)
* `order_id -> orders.id` (CASCADE)
* (extra column: `expiry_date` DATE NULL)

`book_order`

* `book_id -> books.id` (CASCADE)
* `order_id -> orders.id` (CASCADE)

`coupon_course`

* `coupon_id -> coupons.id` (CASCADE)
* `course_id -> courses.id` (CASCADE)

`question_result`

* `result_id -> results.id` (CASCADE)
* `question_id -> questions.id` (CASCADE)
* `option_id -> options.id` (CASCADE)
* (extra columns: `id` PK, `points` INT DEFAULT 0, timestamps)

`user_permissions` (Spatie, composite PK permission_id+user_id+model_type)

* `permission_id -> permissions.id` (CASCADE)

`user_roles` (Spatie, composite PK role_id+user_id+model_type)

* `role_id -> roles.id` (CASCADE)

`role_permissions` (Spatie, composite PK permission_id+role_id)

* `permission_id -> permissions.id` (CASCADE)
* `role_id -> roles.id` (CASCADE)

`telescope_entries_tags` [package]

* `entry_uuid -> telescope_entries.uuid` (CASCADE)

## Eloquent-only relationships (no matching DB-level FK)

* `users.interested_course` (INT) — application-level reference, no FK.
* `categories.parent_id` (INT) — self-referencing parent/child in Eloquent only; also a type mismatch (INT vs BIGINT UNSIGNED) if a FK were ever added.
* `Coupon::orders()` — hasMany via `orders.signature` ↔ `coupons.code` (non-key VARCHAR columns, no FK possible).
* `complaints.created_by` (VARCHAR) — likely stores a user name/id, no FK.

---

# Unverified / Suspicious Database Usage

| # | File | Location | Problem | Recommended verification |
| - | ---- | -------- | ------- | ------------------------ |
| 1 | `database/migrations/2022_11_21_154632_add_bank_code_to_items.php` | `up()` line 16-19, `down()` line 29 | Filename and `down()` reference a table `items` that **does not exist** anywhere in the project (no migration, no model); `up()` actually modifies `orders`. | Confirm no `items` table exists in the live DB; the `down()` will fail if run. |
| 2 | `database/migrations/2022_05_05_211034_create_question_result_pivot_table.php` | `down()` line 42 | `down()` drops `question_result_pivot`, but the table created is `question_result`. Rollback of this migration would fail. | Verify migration history in live DB (`migrations` table) — it has likely never been rolled back. |
| 3 | `database/migrations/2014_10_12_000000_create_users_table.php` | line 23 | `users.interested_course` INT nullable — name implies a course reference but no FK and no Eloquent relationship uses it. | Check how the column is populated/used before relying on it. |
| 4 | `database/migrations/2021_12_26_154424_create_categories_table.php` | line 24 | `categories.parent_id` is INT (signed) while `categories.id` is BIGINT UNSIGNED — no FK, and a FK cannot be added without a type change. | Verify intended self-referencing integrity is enforced only in app code. |
| 5 | `app/Models/Coupon.php` | line 56 | `orders()` hasMany(Order, 'signature', 'code') — relationship over non-key VARCHAR columns; `orders.signature` doubles as a coupon-code store. | Verify semantics of `orders.signature` (payment signature vs coupon code) in payment services. |
| 6 | `app/Models/ZoomUser.php` | whole file | Model declares no `user()` belongsTo despite `zoom_users.user_id` FK existing. | Not a schema issue; note only. |
| 7 | `app/Models/Lecture.php` | `$fillable` | `youtube_id`, `upload_status`, `upload_error` columns exist (2024-12 migration) but are absent from `$fillable` — mass assignment of these would silently fail. | Check how YouTube upload jobs write these columns. |
| 8 | `app/Models/QuizFile.php` | `$fillable` | `section_id` / `question_id` FK columns exist but are not fillable. | Verify files are attached via relation methods, not mass assignment. |
| 9 | `app/Models/Section.php` | `$fillable` | `description` column exists but is not fillable. | Minor; verify admin forms don't mass-assign it. |
| 10 | `database/migrations/2022_02_28_161243_create_book_course_table.php` | whole file | Pivot `book_course` has FKs but **no model relationship uses it** (Book↔Course now goes through `books.course_id` since 2023-08). Probable legacy/deprecated table. | Confirm with data whether the table still holds rows in production. |
| 11 | `app/Imports/OrderItemsImport.php` | line 16 | Raw `DB::table('course_order')->insert(...)` — matches schema; flagged only because it bypasses the model. | None. |
| 12 | `database/migrations/2026_08_09_000001_add_youtube_to_file_transfer_jobs_providers.php` | lines 14-15 | Raw `ALTER TABLE ... MODIFY COLUMN` — MySQL-specific; schema of `file_transfer_jobs` cannot be reproduced on other drivers. | Note for any non-MySQL environment. |
| 13 | `database/migrations/2026_08_11_000001_generalize_youtube_tokens_to_google_oauth_tokens.php` | line 32 | Drops unique index by its **original** name `youtube_tokens_account_unique` after renaming the table — works on MySQL (index names survive renames), but is driver-specific. | Verify on the live DB that the index name matches. |
| 14 | `vendor/laravel/telescope` (auto-loaded migration) | — | `telescope_entries*` tables are created by a vendor migration, not present in `database/migrations/`. They will not exist if migrations were run with Telescope's migrations ignored/published differently, or if Telescope was installed after `migrate` ran. | Check live DB for these tables; disable Telescope in production if unused. |
| 15 | `config/permission.php` | table_names | Spatie table names are non-default (`user_permissions`, `user_roles`, `role_permissions`, morph key `user_id`). Any tooling or docs assuming default names (`model_has_roles`, etc.) would be wrong. | Verified against migration — consistent; noted for external tooling. |
| 16 | `orders` table | migration 2022_04_06_222616 | `uuid` column has no UNIQUE index, `amount`/`currency` are VARCHAR (not DECIMAL), `status` is VARCHAR (not ENUM) despite a fixed value set in app code. | Confirm acceptable for reporting/integrity requirements. |
| 17 | `quiz_files` table | migration 2022_03_13_171111 | No `deleted_at` although most sibling tables use soft deletes; `QuizFile` model has no SoftDeletes — consistent, but deletes are hard. | Note only. |

---

## Analysis Notes

* **Sources inspected:**
  * All 65 files in `database/migrations/` (read in full).
  * All 31 models in `app/Models/` (read in full) — no Eloquent models exist elsewhere in `app/` (verified by grep for `extends Model` / `extends Authenticatable`).
  * `config/database.php`, `config/permission.php`, `config/audit.php`, `config/telescope.php`, `config/queue.php`, `config/session.php`, `.env` (driver/prefix/connection verification).
  * Project-wide grep for `DB::table`, `DB::select`, `DB::statement`, `->from(`, `belongsToMany`, `morphTo`/`morphMany`/`morphOne`/`morphToMany`, `protected $table`, `protected $connection`, `Schema::` outside migrations, and `->connection(` (no secondary connections found).
  * `database/seeders/` and `database/factories/` (model-based; no extra tables).
  * Vendor migration for `laravel/telescope` (only package that auto-creates tables and is registered in `config/app.php`).
* **No SQL dump / schema file exists in the repository**, so this document represents the **migration-defined schema** (final state after applying all migrations chronologically), not the actual live database. The live DB may drift (e.g., failed/partial migrations, manual changes, the Telescope tables if they were never migrated).
* **Column types** are translated from Laravel Schema Builder to MySQL 5.7/8 semantics (`string()` → `VARCHAR(255)`, `boolean()` → `TINYINT(1)`, `uuid()` → `CHAR(36)`, `ipAddress()` → `VARCHAR(45)`, `id()`/`foreignId()` → `BIGINT UNSIGNED`). `timestamps()`/`softDeletes()` produce nullable `TIMESTAMP` columns.
* **Migrations applied chronologically**, including: column additions via `$table->after()` closures, `->change()` modifications on `books` (price/discount defaults, file nullable), the `youtube_tokens` → `google_oauth_tokens` rename + restructure, and the raw `ALTER TABLE` enum modification on `file_transfer_jobs`.
* **Assumptions avoided:** no FKs were inferred from Eloquent relationships (only migration-declared `foreign()`/`constrained()` are listed as database constraints); index names not explicitly given in migrations are shown with Laravel's conventional generated names; no column lengths were guessed beyond Laravel defaults.
* **Not verified:** exact index names as they exist in the live database (Laravel auto-generates them), the contents of the `migrations` table (which migrations actually ran), and any tables created manually outside migrations.
* The Laravel project itself was not modified; only this documentation file (`docs/injazedu-db-schema.md`) was created.
