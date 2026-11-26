"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-26 12:52:01.755617
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INITIAL_PROMPT = """You triage customer support messages. Return a triage record for the message.

intent: billing, shipping, technical_issue, or other when none of these fits.
urgency: high when the customer needs help immediately, low when it can wait, otherwise normal.

Answer with the triage record only."""


def upgrade() -> None:
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.String(),
            server_default=sa.text("(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["prompt_versions.id"],
            name=op.f("fk_prompt_versions_parent_id_prompt_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_versions")),
    )
    op.create_table(
        "prompt_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("active_version_id", sa.Integer(), nullable=False),
        sa.Column(
            "updated_at",
            sa.String(),
            server_default=sa.text("(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_prompt_state_single_row")),
        sa.ForeignKeyConstraint(
            ["active_version_id"],
            ["prompt_versions.id"],
            name=op.f("fk_prompt_state_active_version_id_prompt_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_state")),
    )
    op.create_table(
        "reviews",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("base_prompt_id", sa.Integer(), nullable=False),
        sa.Column("candidate_prompt_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("next_attempt_at", sa.String(), nullable=True),
        sa.Column("owner_token", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.String(), nullable=True),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("judge_model", sa.Text(), nullable=False),
        sa.Column("processing_model", sa.Text(), nullable=False),
        sa.Column("evaluation_config", sa.Text(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.String(),
            server_default=sa.text("(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"),
            nullable=False,
        ),
        sa.Column("started_at", sa.String(), nullable=True),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.CheckConstraint(
            "(status = 'completed') = (outcome IS NOT NULL)",
            name=op.f("ck_reviews_outcome_iff_completed"),
        ),
        sa.CheckConstraint(
            "outcome IS NULL OR outcome IN ('promoted', 'rejected', 'no_changes', 'no_proposal', 'insufficient_samples')",
            name=op.f("ck_reviews_outcome_values"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name=op.f("ck_reviews_status_values"),
        ),
        sa.ForeignKeyConstraint(
            ["base_prompt_id"],
            ["prompt_versions.id"],
            name=op.f("fk_reviews_base_prompt_id_prompt_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["candidate_prompt_id"],
            ["prompt_versions.id"],
            name=op.f("fk_reviews_candidate_prompt_id_prompt_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reviews")),
        sa.UniqueConstraint("candidate_prompt_id", name=op.f("uq_reviews_candidate_prompt_id")),
    )
    with op.batch_alter_table("reviews", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_reviews_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_reviews_request_id"), ["request_id"], unique=False)
    # At most one review is open (Prompt Improvement FR-1); autogenerate cannot see this index.
    op.execute(
        "CREATE UNIQUE INDEX uq_reviews_one_open ON reviews ((1)) "
        "WHERE status IN ('pending', 'running')"
    )

    op.create_table(
        "samples",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("prompt_version_id", sa.Integer(), nullable=False),
        sa.Column("input", sa.Text(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("model_config", sa.Text(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "created_at",
            sa.String(),
            server_default=sa.text("(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider IN ('simulator', 'ollama')", name=op.f("ck_samples_provider_values")
        ),
        sa.CheckConstraint("json_valid(output)", name=op.f("ck_samples_output_json")),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["prompt_versions.id"],
            name=op.f("fk_samples_prompt_version_id_prompt_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_samples")),
    )
    with op.batch_alter_table("samples", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_samples_created_at"), ["created_at"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_samples_prompt_version_id_created_at"),
            ["prompt_version_id", "created_at"],
            unique=False,
        )
        batch_op.create_index(batch_op.f("ix_samples_request_id"), ["request_id"], unique=False)

    op.create_table(
        "idempotency_requests",
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("sample_id", sa.Text(), nullable=True),
        sa.Column("owner_token", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.String(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.String(),
            server_default=sa.text("(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.String(),
            server_default=sa.text("(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'completed', 'retryable_failed', 'failed')",
            name=op.f("ck_idempotency_requests_status_values"),
        ),
        sa.CheckConstraint(
            "response_body IS NULL OR json_valid(response_body)",
            name=op.f("ck_idempotency_requests_response_body_json"),
        ),
        sa.ForeignKeyConstraint(
            ["sample_id"], ["samples.id"], name=op.f("fk_idempotency_requests_sample_id_samples")
        ),
        sa.PrimaryKeyConstraint("endpoint", "key", name=op.f("pk_idempotency_requests")),
    )
    with op.batch_alter_table("idempotency_requests", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_idempotency_requests_created_at"), ["created_at"], unique=False
        )

    op.create_table(
        "llm_calls",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("sample_id", sa.Text(), nullable=True),
        sa.Column("review_id", sa.Text(), nullable=True),
        sa.Column("prompt_version_id", sa.Integer(), nullable=True),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("provider_request_id", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.String(),
            server_default=sa.text("(strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.String(), nullable=True),
        sa.CheckConstraint(
            "operation IN ('process', 'judge', 'improve_prompt', 'evaluate_candidate')",
            name=op.f("ck_llm_calls_operation_values"),
        ),
        sa.CheckConstraint(
            "status IN ('running', 'success', 'error', 'timeout')",
            name=op.f("ck_llm_calls_status_values"),
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["prompt_versions.id"],
            name=op.f("fk_llm_calls_prompt_version_id_prompt_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["review_id"], ["reviews.id"], name=op.f("fk_llm_calls_review_id_reviews")
        ),
        sa.ForeignKeyConstraint(
            ["sample_id"], ["samples.id"], name=op.f("fk_llm_calls_sample_id_samples")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
    )
    with op.batch_alter_table("llm_calls", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_llm_calls_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_llm_calls_request_id"), ["request_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_llm_calls_review_id"), ["review_id"], unique=False)

    op.create_table(
        "review_judgments",
        sa.Column("review_id", sa.Text(), nullable=False),
        sa.Column("sample_id", sa.Text(), nullable=False),
        sa.Column("prompt_version_id", sa.Integer(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("expected_output", sa.JSON(), nullable=True),
        sa.Column("judge_explanation", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "expected_output IS NULL OR json_valid(expected_output)",
            name=op.f("ck_review_judgments_expected_output_json"),
        ),
        sa.CheckConstraint("json_valid(output)", name=op.f("ck_review_judgments_output_json")),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["prompt_versions.id"],
            name=op.f("fk_review_judgments_prompt_version_id_prompt_versions"),
        ),
        sa.ForeignKeyConstraint(
            ["review_id"], ["reviews.id"], name=op.f("fk_review_judgments_review_id_reviews")
        ),
        sa.ForeignKeyConstraint(
            ["sample_id"], ["samples.id"], name=op.f("fk_review_judgments_sample_id_samples")
        ),
        sa.PrimaryKeyConstraint(
            "review_id", "sample_id", "prompt_version_id", name=op.f("pk_review_judgments")
        ),
    )
    with op.batch_alter_table("review_judgments", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_review_judgments_sample_id"), ["sample_id"], unique=False
        )

    # Version 1 (Processing FR-2). It names billing, shipping and technical_issue but not
    # cancellation or account, so a review has something to improve (simulator.md).
    op.execute(
        sa.text(
            "INSERT INTO prompt_versions (id, parent_id, content, change_reason) "
            "VALUES (1, NULL, :content, 'Initial prompt')"
        ).bindparams(content=INITIAL_PROMPT)
    )
    op.execute("INSERT INTO prompt_state (id, active_version_id) VALUES (1, 1)")


def downgrade() -> None:
    with op.batch_alter_table("review_judgments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_review_judgments_sample_id"))

    op.drop_table("review_judgments")
    with op.batch_alter_table("llm_calls", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_llm_calls_review_id"))
        batch_op.drop_index(batch_op.f("ix_llm_calls_request_id"))
        batch_op.drop_index(batch_op.f("ix_llm_calls_created_at"))

    op.drop_table("llm_calls")
    with op.batch_alter_table("idempotency_requests", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_idempotency_requests_created_at"))

    op.drop_table("idempotency_requests")
    with op.batch_alter_table("samples", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_samples_request_id"))
        batch_op.drop_index(batch_op.f("ix_samples_prompt_version_id_created_at"))
        batch_op.drop_index(batch_op.f("ix_samples_created_at"))

    op.drop_table("samples")
    with op.batch_alter_table("reviews", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_reviews_request_id"))
        batch_op.drop_index(batch_op.f("ix_reviews_created_at"))

    op.execute("DROP INDEX uq_reviews_one_open")
    op.drop_table("reviews")
    op.drop_table("prompt_state")
    op.drop_table("prompt_versions")
