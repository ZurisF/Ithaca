"""Run with: uv run --extra embedding python scripts/import_question_bank.py."""

import argparse
import json

from app.bank.seed import import_seed_batch, load_seed_batch


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the reviewed 11 topic files")
    parser.add_argument(
        "--dry-run", action="store_true", help="check source counts without loading BGE-M3"
    )
    parser.add_argument(
        "--model-path", default="BAAI/bge-m3", help="BGE-M3 model ID or local snapshot path"
    )
    args = parser.parse_args()
    batch = load_seed_batch()
    if args.dry_run:
        print(
            json.dumps(
                {
                    "source_total": batch.source_total,
                    "source_duplicates": batch.source_duplicates,
                    "source_unique": len(batch.questions),
                }
            )
        )
        return

    import asyncio

    class BGE:
        def encode_corpus(self, questions: list[str]) -> list[list[float]]:
            from FlagEmbedding import BGEM3FlagModel

            model = BGEM3FlagModel(args.model_path, use_fp16=False)
            output = model.encode_corpus(
                questions,
                batch_size=16,
                max_length=512,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            return output["dense_vecs"].tolist()

    stats = asyncio.run(import_seed_batch(batch, BGE()))
    print(json.dumps(stats.__dict__, ensure_ascii=False))


if __name__ == "__main__":
    main()
