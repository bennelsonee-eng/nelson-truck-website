"""Run our MVP3 plow image through Microsoft TRELLIS HuggingFace Space."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from gradio_client import Client, handle_file


SPACE = "microsoft/TRELLIS"
INPUT_IMAGE = "/tmp/test_trellis_mvp3.jpg"
OUTPUT_DIR = Path("/tmp/trellis_out")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Connecting to {SPACE}...")
    client = Client(SPACE)
    print("Connected.")

    # Step 1: start session
    print("\n[1/4] Starting session...")
    try:
        client.predict(api_name="/start_session")
    except Exception as e:
        print(f"  start_session: {e}")

    # Step 2: preprocess image
    print(f"\n[2/4] Preprocessing image: {INPUT_IMAGE}")
    t0 = time.time()
    preprocessed = client.predict(
        image=handle_file(INPUT_IMAGE),
        api_name="/preprocess_image",
    )
    print(f"  preprocessed in {time.time() - t0:.1f}s")
    print(f"  result: {preprocessed}")
    if isinstance(preprocessed, dict) and "path" in preprocessed:
        import shutil
        shutil.copy(preprocessed["path"], OUTPUT_DIR / "preprocessed.png")

    # Step 3: image to 3D
    print(f"\n[3/4] Running image_to_3d (this may take a while)...")
    t0 = time.time()
    seed_value = 0
    try:
        result_3d = client.predict(
            image=handle_file(INPUT_IMAGE),
            multiimages=[],
            seed=seed_value,
            ss_guidance_strength=7.5,
            ss_sampling_steps=12,
            slat_guidance_strength=3.0,
            slat_sampling_steps=12,
            multiimage_algo="stochastic",
            api_name="/image_to_3d",
        )
        print(f"  done in {time.time() - t0:.1f}s")
        print(f"  result type: {type(result_3d)}")
        if isinstance(result_3d, (list, tuple)):
            for i, r in enumerate(result_3d):
                print(f"    [{i}] {r}")
        else:
            print(f"  {result_3d}")
    except Exception as e:
        print(f"  image_to_3d failed: {e}")
        return 1

    # Step 4: extract GLB
    print(f"\n[4/4] Extracting GLB mesh...")
    t0 = time.time()
    try:
        glb_result = client.predict(
            mesh_simplify=0.95,
            texture_size=1024,
            api_name="/extract_glb",
        )
        print(f"  done in {time.time() - t0:.1f}s")
        print(f"  glb result: {glb_result}")
        if isinstance(glb_result, (list, tuple)):
            for i, r in enumerate(glb_result):
                print(f"    [{i}] {r}")
                if isinstance(r, str) and r.endswith(".glb"):
                    import shutil
                    out_path = OUTPUT_DIR / f"mvp3_trellis_{i}.glb"
                    shutil.copy(r, out_path)
                    print(f"    saved: {out_path}")
        elif isinstance(glb_result, str) and glb_result.endswith(".glb"):
            import shutil
            out_path = OUTPUT_DIR / "mvp3_trellis.glb"
            shutil.copy(glb_result, out_path)
            print(f"  saved: {out_path}")
    except Exception as e:
        print(f"  extract_glb failed: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
