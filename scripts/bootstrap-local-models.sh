#!/usr/bin/env bash
set -Eeuo pipefail

model_dir="${1:-/srv/kairos/models}"
model_dir="$(realpath -m -- "$model_dir")"
case "$model_dir" in
  /srv/kairos/models) ;;
  *) echo "refusing model output outside /srv/kairos/models" >&2; exit 65 ;;
esac

install -d -m 0750 -- "$model_dir"

download_verified() {
  local name="$1" url="$2" expected_size="$3" expected_sha="$4"
  local target="$model_dir/$name" partial="$model_dir/.$name.part"
  if [[ -f "$target" ]] && [[ "$(stat -c %s -- "$target")" == "$expected_size" ]] \
    && echo "$expected_sha  $target" | sha256sum --check --status; then
    echo "MODEL_PRESENT=$name"
    return
  fi
  rm -f -- "$partial"
  curl --fail --location --retry 5 --retry-all-errors --connect-timeout 20 \
    --output "$partial" -- "$url"
  [[ "$(stat -c %s -- "$partial")" == "$expected_size" ]]
  echo "$expected_sha  $partial" | sha256sum --check --status
  chmod 0640 -- "$partial"
  mv -f -- "$partial" "$target"
  echo "MODEL_VERIFIED=$name"
}

download_verified \
  "Qwen3-1.7B-Q4_K_M.gguf" \
  "https://huggingface.co/ggml-org/Qwen3-1.7B-GGUF/resolve/daeb8e2d528a760970442092f6bf1e55c3b659eb/Qwen3-1.7B-Q4_K_M.gguf" \
  "1282439264" \
  "d2387ca2dbfee2ffabce7120d3770dadca0b293052bc2f0e138fdc940d9bc7b5"

download_verified \
  "multilingual-e5-small-Q8_0.gguf" \
  "https://huggingface.co/keisuke-miyako/multilingual-e5-small-gguf-q8_0/resolve/e1da94460f223e3204e75dfe51350e5491c879d4/multilingual-e5-small-Q8_0.gguf" \
  "131953504" \
  "0d5a5a0b0ad84faad6357a6145e769b0661f0efbf53acf74598afc34dab454f4"

install -m 0640 -- /opt/kairos/current/config/localai/qwen3-1.7b-kairos.yaml "$model_dir/qwen3-1.7b-kairos.yaml"
install -m 0640 -- /opt/kairos/current/config/localai/multilingual-e5-small.yaml "$model_dir/multilingual-e5-small.yaml"
echo "LOCAL_MODELS_BOOTSTRAP=PASS"
