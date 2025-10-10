
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