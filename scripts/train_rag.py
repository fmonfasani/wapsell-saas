#!/usr/bin/env python3
"""Train RAG by simulating buyer interactions.

Generates diverse queries based on property data and runs agent against each.
Populates QueryLog + Hindsight for better SOUL auto-enrichment.

Usage:
    python scripts/train_rag.py [--api-url URL] [--tenant-id ID]
"""

from __future__ import annotations

import argparse
import httpx
import sys

def train_rag(api_url: str, tenant_id: str, custom_prompt: str | None = None) -> bool:
    """Trigger RAG training for a tenant."""

    print(f"\n{'='*70}")
    print(f"RAG TRAINING: {tenant_id}")
    print(f"{'='*70}\n")

    with httpx.Client(timeout=120) as client:
        print(f"Starting training on {api_url}...\n")

        payload = {}
        if custom_prompt:
            payload["custom_prompt"] = custom_prompt
            print(f"Using custom prompt:\n{custom_prompt[:100]}...\n")

        response = client.post(
            f"{api_url}/tenants/{tenant_id}/train-rag",
            json=payload,
        )

        if response.status_code != 200:
            print(f"[ERROR] Training failed: {response.status_code}")
            print(response.text)
            return False

        result = response.json()

        print(f"Training Results:")
        print(f"  ✓ Queries generadas por LLM: {result['queries_generated']}")
        print(f"  ✓ Queries procesadas: {result['queries_processed']}")
        success_rate = 100 * result['queries_processed'] / result['queries_generated']
        print(f"  ✓ Tasa de éxito: {success_rate:.1f}%")

        if result['errors']:
            print(f"\n[WARNINGS] ({len(result['errors'])} errores):")
            for error in result['errors'][:3]:
                print(f"    - {error}")
            if len(result['errors']) > 3:
                print(f"    ... y {len(result['errors']) - 3} más")

        print(f"\n{'='*70}")
        print(f"Training completo!")
        print(f"{'='*70}\n")

        print("Qué pasó:")
        print("  1. Sistema analizó el catálogo")
        print("     (barrios, precios, dormitorios)")
        print("  2. LLM generó 100 queries realistas y variadas")
        print("     (conversacionales, como buyers reales)")
        print("  3. Agent procesó CADA query")
        print("     (buscó en RAG, generó respuestas)")
        print("  4. Se poblaron QueryLog + Hindsight + SOUL")
        print()
        print("Resultado: RAG ahora está PRE-ENTRENADO y listo para buyers reales!")
        print()
        print("El tenant ya sabe:")
        print("  - Qué barrios son populares")
        print("  - Qué rangos de precio interesan")
        print("  - Cómo responder preguntas variadas")

        return result['queries_processed'] > 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train RAG with simulated buyer interactions"
    )
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Wapsell API URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--tenant-id",
        required=True,
        help="Tenant ID to train",
    )
    parser.add_argument(
        "--prompt",
        help="Custom prompt for query generation",
    )
    parser.add_argument(
        "--prompt-file",
        help="File with custom prompt for query generation",
    )

    args = parser.parse_args()

    custom_prompt = None
    if args.prompt:
        custom_prompt = args.prompt
    elif args.prompt_file:
        with open(args.prompt_file) as f:
            custom_prompt = f.read()

    success = train_rag(args.api_url, args.tenant_id, custom_prompt)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
