-- Studio presentation tables. Run as the configured Oracle user.
-- Fresh schema only. The API also creates any missing tables on startup.
CREATE TABLE "GENAI_WORKSPACE_STUDIO_USER" (
	id RAW(16) NOT NULL, 
	username VARCHAR2(128 CHAR) NOT NULL, 
	external_subject VARCHAR2(256 CHAR), 
	admin_slot VARCHAR2(32 CHAR), 
	hashed_password VARCHAR2(1024 CHAR) NOT NULL, 
	is_active SMALLINT DEFAULT 1 NOT NULL, 
	is_superuser SMALLINT DEFAULT 0 NOT NULL, 
	is_verified SMALLINT DEFAULT 1 NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE, 
	auth_version INTEGER DEFAULT 1 NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (admin_slot), 
	CONSTRAINT ck_studio_user_is_active_bool CHECK (is_active IN (0, 1)), 
	CONSTRAINT ck_studio_user_is_superuser_bool CHECK (is_superuser IN (0, 1)), 
	CONSTRAINT ck_studio_user_is_verified_bool CHECK (is_verified IN (0, 1))
);

CREATE UNIQUE INDEX "ix_GENAI_WORKSPACE_STUDIO_USER_external_subject" ON "GENAI_WORKSPACE_STUDIO_USER" (external_subject);

CREATE UNIQUE INDEX "ix_GENAI_WORKSPACE_STUDIO_USER_username" ON "GENAI_WORKSPACE_STUDIO_USER" (username);

CREATE TABLE "GENAI_WORKSPACE_IMAGE_ASSET" (
	id RAW(16) NOT NULL, 
	owner_id RAW(16), 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	is_uploaded SMALLINT NOT NULL, 
	path CLOB NOT NULL, 
	extras CLOB, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES "GENAI_WORKSPACE_STUDIO_USER" (id) ON DELETE CASCADE, 
	CONSTRAINT ck_image_asset_is_uploaded_bool CHECK (is_uploaded IN (0, 1)), 
	CONSTRAINT ck_image_asset_extras_json CHECK (extras IS JSON)
);

CREATE INDEX "ix_GENAI_WORKSPACE_IMAGE_ASSET_owner_id" ON "GENAI_WORKSPACE_IMAGE_ASSET" (owner_id);

CREATE TABLE "GENAI_WORKSPACE_PRESENTATION" (
	id RAW(16) NOT NULL, 
	owner_id RAW(16), 
	version VARCHAR2(11 CHAR) NOT NULL, 
	content CLOB NOT NULL, 
	n_slides INTEGER NOT NULL, 
	language VARCHAR2(64 CHAR) NOT NULL, 
	title CLOB, 
	file_paths CLOB, 
	outlines CLOB, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	layout CLOB, 
	structure CLOB, 
	instructions CLOB, 
	tone VARCHAR2(64 CHAR), 
	verbosity VARCHAR2(64 CHAR), 
	is_favorite SMALLINT DEFAULT 0 NOT NULL, 
	include_table_of_contents SMALLINT, 
	include_title_slide SMALLINT, 
	web_search SMALLINT, 
	web_search_mode VARCHAR2(64 CHAR), 
	theme CLOB, 
	fonts CLOB, 
	generation_mode VARCHAR2(64 CHAR) NOT NULL, 
	community_design_ids CLOB, 
	smart_template VARCHAR2(255 CHAR), 
	smart_brand_colors CLOB, 
	generation_status VARCHAR2(64 CHAR), 
	has_explicit_slide_structure SMALLINT, 
	source_quality_flags CLOB, 
	acknowledged_quality_flag_groups CLOB, 
	outline_generation_id RAW(16), 
	deck_generation_id RAW(16), 
	source_presentation_id RAW(16), 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES "GENAI_WORKSPACE_STUDIO_USER" (id) ON DELETE CASCADE, 
	FOREIGN KEY(source_presentation_id) REFERENCES "GENAI_WORKSPACE_PRESENTATION" (id) ON DELETE SET NULL, 
	CONSTRAINT presentation_version CHECK (version IN ('v1-standard', 'v2-standard')), 
	CONSTRAINT ck_presentation_file_paths_json CHECK (file_paths IS JSON), 
	CONSTRAINT ck_presentation_outlines_json CHECK (outlines IS JSON), 
	CONSTRAINT ck_presentation_layout_json CHECK (layout IS JSON), 
	CONSTRAINT ck_presentation_structure_json CHECK (structure IS JSON), 
	CONSTRAINT ck_presentation_is_favorite_bool CHECK (is_favorite IN (0, 1)), 
	CONSTRAINT ck_presentation_include_table_of_contents_bool CHECK (include_table_of_contents IN (0, 1)), 
	CONSTRAINT ck_presentation_include_title_slide_bool CHECK (include_title_slide IN (0, 1)), 
	CONSTRAINT ck_presentation_web_search_bool CHECK (web_search IN (0, 1)), 
	CONSTRAINT ck_presentation_theme_json CHECK (theme IS JSON), 
	CONSTRAINT ck_presentation_fonts_json CHECK (fonts IS JSON), 
	CONSTRAINT ck_presentation_community_design_ids_json CHECK (community_design_ids IS JSON), 
	CONSTRAINT ck_presentation_smart_brand_colors_json CHECK (smart_brand_colors IS JSON), 
	CONSTRAINT ck_presentation_has_explicit_slide_structure_bool CHECK (has_explicit_slide_structure IN (0, 1)), 
	CONSTRAINT ck_presentation_source_quality_flags_json CHECK (source_quality_flags IS JSON), 
	CONSTRAINT ck_presentation_acknowledged_quality_flag_groups_json CHECK (acknowledged_quality_flag_groups IS JSON)
);

CREATE INDEX "ix_GENAI_WORKSPACE_PRESENTATION_owner_id" ON "GENAI_WORKSPACE_PRESENTATION" (owner_id);

CREATE INDEX "ix_GENAI_WORKSPACE_PRESENTATION_source_presentation_id" ON "GENAI_WORKSPACE_PRESENTATION" (source_presentation_id);

CREATE TABLE "GENAI_WORKSPACE_SLIDE" (
	id RAW(16) NOT NULL, 
	owner_id RAW(16), 
	presentation RAW(16), 
	layout_group VARCHAR2(255 CHAR) NOT NULL, 
	layout VARCHAR2(255 CHAR) NOT NULL, 
	"index" INTEGER NOT NULL, 
	content CLOB, 
	html_content CLOB, 
	speaker_note CLOB, 
	properties CLOB, 
	ui CLOB, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES "GENAI_WORKSPACE_STUDIO_USER" (id) ON DELETE CASCADE, 
	FOREIGN KEY(presentation) REFERENCES "GENAI_WORKSPACE_PRESENTATION" (id) ON DELETE CASCADE, 
	CONSTRAINT ck_slide_content_json CHECK (content IS JSON), 
	CONSTRAINT ck_slide_properties_json CHECK (properties IS JSON), 
	CONSTRAINT ck_slide_ui_json CHECK (ui IS JSON)
);

CREATE INDEX "ix_GENAI_WORKSPACE_SLIDE_owner_id" ON "GENAI_WORKSPACE_SLIDE" (owner_id);

CREATE INDEX "ix_GENAI_WORKSPACE_SLIDE_presentation" ON "GENAI_WORKSPACE_SLIDE" (presentation);

CREATE TABLE "GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE" (
	id RAW(16) NOT NULL, 
	owner_id RAW(16), 
	presentation_id RAW(16), 
	conversation_id RAW(16) NOT NULL, 
	position INTEGER NOT NULL, 
	role VARCHAR2(32 CHAR) NOT NULL, 
	content CLOB NOT NULL, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	tool_calls CLOB, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES "GENAI_WORKSPACE_STUDIO_USER" (id) ON DELETE CASCADE, 
	FOREIGN KEY(presentation_id) REFERENCES "GENAI_WORKSPACE_PRESENTATION" (id) ON DELETE CASCADE, 
	CONSTRAINT ck_studio_chat_message_tool_calls_json CHECK (tool_calls IS JSON)
);

CREATE INDEX "ix_GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE_conversation_id" ON "GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE" (conversation_id);

CREATE INDEX "ix_GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE_owner_id" ON "GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE" (owner_id);

CREATE INDEX "ix_GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE_position" ON "GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE" (position);

CREATE INDEX "ix_GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE_presentation_id" ON "GENAI_WORKSPACE_STUDIO_CHAT_MESSAGE" (presentation_id);

CREATE TABLE "GENAI_WORKSPACE_STUDIO_FEEDBACK" (
	id RAW(16) NOT NULL, 
	owner_id RAW(16), 
	presentation_id RAW(16), 
	stage VARCHAR2(16 CHAR) NOT NULL, 
	generation_id RAW(16) NOT NULL, 
	rating SMALLINT NOT NULL, 
	reasons CLOB, 
	"comment" CLOB, 
	context CLOB, 
	created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(owner_id) REFERENCES "GENAI_WORKSPACE_STUDIO_USER" (id) ON DELETE CASCADE, 
	FOREIGN KEY(presentation_id) REFERENCES "GENAI_WORKSPACE_PRESENTATION" (id) ON DELETE SET NULL, 
	CONSTRAINT uq_generation_feedback_owner_generation UNIQUE (owner_id, presentation_id, stage, generation_id), 
	CONSTRAINT ck_studio_feedback_reasons_json CHECK (reasons IS JSON), 
	CONSTRAINT ck_studio_feedback_context_json CHECK (context IS JSON)
);

CREATE INDEX "ix_GENAI_WORKSPACE_STUDIO_FEEDBACK_owner_id" ON "GENAI_WORKSPACE_STUDIO_FEEDBACK" (owner_id);

CREATE INDEX "ix_GENAI_WORKSPACE_STUDIO_FEEDBACK_presentation_id" ON "GENAI_WORKSPACE_STUDIO_FEEDBACK" (presentation_id);
