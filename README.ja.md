
# fujielab-moshi-client

Fujie lab. version of Moshi client library for Python programs.

## 概要
音声アシスタントやチャットボットのための Moshi クライアントライブラリです。WebSocket 経由で音声データやテキストデータの送受信が可能です。

## インストール
```bash
pip install fujielab-moshi-client
```

もしくは、リポジトリをクローンして requirements.txt で依存関係をインストール:
```bash
pip install -r requirements.txt
```

## 使い方
### MoshiClient クラスの利用例
```python
from fujielab.moshi.moshi_client_lib import MoshiClient
import numpy as np

# MoshiClientの初期化
client = MoshiClient()

# サーバーへ接続（ブロッキング）
client.connect("ws://localhost:8998/api/chat")

# 音声データ（PCM float32, 1次元np.array）を送信
audio_data = np.array([...], dtype=np.float32)
client.add_audio_input(audio_data)

# サーバーからの音声データを取得
received_audio = client.get_audio_output()

# サーバーからのテキスト応答を取得
text_response = client.get_text_output()

# 切断
client.disconnect()
```

## MoshiClientのパラメータ
- text_temperature: テキスト生成の温度パラメータ（デフォルト: 0.7）
- text_topk: テキスト生成のTop-Kサンプリング（デフォルト: 25）
- audio_temperature: 音声生成の温度パラメータ（デフォルト: 0.8）
- audio_topk: 音声生成のTop-Kサンプリング（デフォルト: 250）
- pad_mult: 音声パディングの倍率（デフォルト: 0.0）
- repetition_penalty: 繰り返し抑制のペナルティ（デフォルト: 1.0）
- repetition_penalty_context: 繰り返し抑制のコンテキスト長（デフォルト: 64）
- output_buffer_size: 音声出力バッファのサイズ（デフォルト: 1920サンプル）

### 音声フレームサイズについて

**音声入力（add_audio_input）**:
- 任意のサイズの音声データを送信可能です
- 内部で自動的に適切なサイズ（1920サンプル）にバッファリングされ、Moshiサーバーに送信されます
- 例：160サンプル、480サンプル、2000サンプル等、どのようなサイズでも対応

**音声出力（get_audio_output）**:
- 出力される音声データのサイズは `MoshiClient` のコンストラクタで指定する必要があります
- `output_buffer_size` パラメータで指定（デフォルト: 1920サンプル）
- 例：
```python
# 480サンプル（20ms @ 24kHz）ずつ取得したい場合
client = MoshiClient(output_buffer_size=480)

# 960サンプル（40ms @ 24kHz）ずつ取得したい場合
client = MoshiClient(output_buffer_size=960)
```

**注意点**:
Moshiサーバーは80ms（1920サンプル）単位で音声を生成します．
そのため運用上以下の点に注意する必要があります．
- `add_audio_input`で1920サンプル未満のデータを与えた場合，すぐにはMoshiサーバーに送信されません．
  内部バッファにデータが蓄積され，1920サンプルに達した時点でまとめて送信されます．
- Moshiサーバーにデータが送信される前に`get_audio_output`を呼び出しても，音声データは返されません．

### シンプルなクライアントの実行
```bash
python -m fujielab.moshi.simple_moshi_client
```

## 依存パッケージ
- websockets
- sounddevice
- numpy
- opuslib

## ライセンス
Apache License 2.0
See [LICENSE](LICENSE) for details.