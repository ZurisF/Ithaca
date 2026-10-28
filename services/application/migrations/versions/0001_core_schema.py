"""Core business schema and database invariants.

Revision ID: 0001_core_schema
Revises:
"""

from alembic import op

revision = "0001_core_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE SCHEMA app")
    op.execute("CREATE SCHEMA bank")
    op.execute("CREATE SCHEMA telemetry")
    op.execute("""
        CREATE TABLE app.users (
            id uuid PRIMARY KEY,
            role text NOT NULL CHECK (role IN ('user', 'administrator')),
            display_name text,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE app.interview_sessions (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES app.users(id),
            status text NOT NULL DEFAULT 'preparing'
                CHECK (status IN ('preparing','interviewing','post_processing','completed','aborted')),
            interview_direction text CHECK (interview_direction IN (
                'project_overview','core_flow_deep_dive','cross_cutting',
                'stress_interview','contribution_retrospective')),
            selected_sections jsonb NOT NULL DEFAULT '[]'::jsonb
                CHECK (jsonb_typeof(selected_sections) = 'array'),
            source_handle text,
            termination_reason text,
            curation_review boolean NOT NULL DEFAULT false,
            feedback_frozen_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz,
            CONSTRAINT session_terminal_combination CHECK (
                (status IN ('preparing','interviewing') AND termination_reason IS NULL
                    AND feedback_frozen_at IS NULL AND completed_at IS NULL)
                OR (status = 'post_processing' AND termination_reason IN ('normal','early_finish','safety_cap')
                    AND feedback_frozen_at IS NOT NULL AND completed_at IS NULL)
                OR (status = 'completed' AND termination_reason IN ('normal','early_finish','safety_cap')
                    AND feedback_frozen_at IS NOT NULL AND completed_at IS NOT NULL)
                OR (status = 'aborted' AND termination_reason = 'forced_exit'
                    AND feedback_frozen_at IS NOT NULL AND completed_at IS NOT NULL)
            )
        )
    """)
    op.execute(
        "CREATE INDEX sessions_owner_recent ON app.interview_sessions (user_id, updated_at DESC)"
    )
    op.execute("CREATE INDEX sessions_recovery ON app.interview_sessions (status, updated_at)")
    op.execute("""
        CREATE TABLE app.session_snapshots (
            session_id uuid PRIMARY KEY REFERENCES app.interview_sessions(id) ON DELETE CASCADE,
            content text NOT NULL,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE app.interview_plans (
            session_id uuid PRIMARY KEY REFERENCES app.interview_sessions(id) ON DELETE CASCADE,
            plan jsonb NOT NULL CHECK (jsonb_typeof(plan) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE app.stage_results (
            session_id uuid NOT NULL REFERENCES app.interview_sessions(id) ON DELETE CASCADE,
            stage_index integer NOT NULL CHECK (stage_index >= 0),
            stage_id text NOT NULL,
            result text NOT NULL CHECK (result IN ('complete','unresolved')),
            closed_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (session_id, stage_index),
            UNIQUE (session_id, stage_id)
        )
    """)
    op.execute("""
        CREATE TABLE bank.questions (
            id uuid PRIMARY KEY,
            question text NOT NULL UNIQUE CHECK (length(btrim(question)) > 0),
            topic_path text NOT NULL,
            ideal_answer text,
            usage_count bigint NOT NULL DEFAULT 0 CHECK (usage_count >= 0),
            upvote_count bigint NOT NULL DEFAULT 0 CHECK (upvote_count >= 0),
            downvote_count bigint NOT NULL DEFAULT 0 CHECK (downvote_count >= 0),
            embedding vector(1024),
            lexical_document tsvector,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX questions_embedding_hnsw ON bank.questions USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("CREATE INDEX questions_lexical_gin ON bank.questions USING gin (lexical_document)")
    op.execute("CREATE INDEX questions_topic ON bank.questions (topic_path)")
    op.execute("""
        CREATE TABLE app.turns (
            session_id uuid NOT NULL REFERENCES app.interview_sessions(id) ON DELETE CASCADE,
            turn_no integer NOT NULL CHECK (turn_no BETWEEN 1 AND 100),
            stage_index integer NOT NULL CHECK (stage_index >= 0),
            question text NOT NULL CHECK (length(btrim(question)) > 0),
            question_id uuid REFERENCES bank.questions(id) ON DELETE RESTRICT,
            answer text,
            interviewer_message text,
            question_shown_at timestamptz NOT NULL DEFAULT now(),
            answered_at timestamptz,
            PRIMARY KEY (session_id, turn_no),
            CHECK ((answer IS NULL) = (answered_at IS NULL))
        )
    """)
    op.execute(
        "CREATE UNIQUE INDEX turns_one_unanswered ON app.turns (session_id) WHERE answer IS NULL"
    )
    op.execute(
        "CREATE INDEX turns_question ON app.turns (question_id) WHERE question_id IS NOT NULL"
    )
    op.execute("""
        CREATE TABLE app.question_feedback (
            session_id uuid NOT NULL,
            turn_no integer NOT NULL,
            value text NOT NULL CHECK (value IN ('upvote','downvote')),
            reason text CHECK (reason IS NULL OR reason IN ('重复','不相关','表述不清','其他')),
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (session_id, turn_no),
            FOREIGN KEY (session_id, turn_no) REFERENCES app.turns(session_id, turn_no) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE TABLE app.turn_post_results (
            session_id uuid NOT NULL,
            turn_no integer NOT NULL,
            project_answer text,
            ideal_answer text,
            comment text,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (session_id, turn_no),
            FOREIGN KEY (session_id, turn_no) REFERENCES app.turns(session_id, turn_no) ON DELETE CASCADE
        )
    """)
    op.execute("""
        CREATE TABLE app.session_reports (
            session_id uuid PRIMARY KEY REFERENCES app.interview_sessions(id) ON DELETE CASCADE,
            report jsonb NOT NULL CHECK (jsonb_typeof(report) = 'object'),
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE app.post_tasks (
            task_key text PRIMARY KEY,
            session_id uuid NOT NULL REFERENCES app.interview_sessions(id) ON DELETE CASCADE,
            kind text NOT NULL CHECK (kind IN ('project_answers','ideal_answer','evaluation','report')),
            turn_no integer,
            status text NOT NULL CHECK (status IN ('pending','running','succeeded','failed')),
            attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
            last_error_code text,
            lease_owner text,
            lease_expires_at timestamptz,
            started_at timestamptz,
            finished_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK ((kind IN ('project_answers','report') AND turn_no IS NULL)
                OR (kind IN ('ideal_answer','evaluation') AND turn_no IS NOT NULL)),
            FOREIGN KEY (session_id, turn_no) REFERENCES app.turns(session_id, turn_no) ON DELETE CASCADE
        )
    """)
    op.execute("CREATE INDEX post_tasks_session_status ON app.post_tasks (session_id, status)")
    op.execute("""
        CREATE TABLE app.snapshot_append_operations (
            operation_key text PRIMARY KEY,
            session_id uuid NOT NULL REFERENCES app.interview_sessions(id) ON DELETE CASCADE,
            section text NOT NULL CHECK (section IN ('用户意见','事后核验')),
            payload_hash text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE bank.session_settlements (
            session_id uuid PRIMARY KEY REFERENCES app.interview_sessions(id) ON DELETE CASCADE,
            settled_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE TABLE app.curation_items (
            id uuid PRIMARY KEY,
            source_session_id uuid NOT NULL,
            source_turn_no integer NOT NULL,
            status text NOT NULL CHECK (status IN ('pending','reviewed','added','rejected')),
            edited_question text,
            proposed_topic_path text,
            review_notes text,
            reviewed_by uuid REFERENCES app.users(id),
            question_bank_id uuid REFERENCES bank.questions(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            FOREIGN KEY (source_session_id, source_turn_no)
                REFERENCES app.turns(session_id, turn_no) ON DELETE CASCADE,
            CHECK ((status = 'added') = (question_bank_id IS NOT NULL))
        )
    """)
    op.execute("CREATE INDEX curation_source ON app.curation_items (source_session_id)")
    op.execute("""
        CREATE TABLE telemetry.model_calls (
            trace_id uuid PRIMARY KEY,
            span_id text,
            parent_span_id text,
            session_id uuid REFERENCES app.interview_sessions(id) ON DELETE CASCADE,
            operation_name text NOT NULL,
            provider text NOT NULL,
            model text NOT NULL,
            prompt_version text,
            status text NOT NULL,
            attempt_no integer NOT NULL CHECK (attempt_no >= 1),
            started_at timestamptz NOT NULL,
            finished_at timestamptz NOT NULL,
            latency_ms integer NOT NULL CHECK (latency_ms >= 0),
            input_tokens integer CHECK (input_tokens >= 0),
            output_tokens integer CHECK (output_tokens >= 0),
            cost_micros bigint CHECK (cost_micros >= 0),
            error_code text
        )
    """)
    op.execute("CREATE INDEX model_calls_session ON telemetry.model_calls (session_id)")
    op.execute("CREATE INDEX model_calls_retention ON telemetry.model_calls (finished_at)")


def downgrade() -> None:
    op.execute("DROP SCHEMA telemetry CASCADE")
    op.execute("DROP SCHEMA bank CASCADE")
    op.execute("DROP SCHEMA app CASCADE")
