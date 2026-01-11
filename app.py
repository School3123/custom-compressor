import streamlit as st
import zlib
import io

# --- 独自の圧縮・解凍ロジック ---

# 独自のファイルヘッダー（これが一致しないと解凍しない）
FILE_HEADER = b'MY_UNIQUE_ARCHIVE_v1'

def custom_compress(file_bytes: bytes, password_int: int) -> bytes:
    """
    1. zlibで圧縮
    2. パスワード(0-255)を使ってXOR演算で撹拌（独自形式化）
    3. ヘッダーを付与
    """
    # 1. 圧縮
    compressed_data = zlib.compress(file_bytes, level=9)
    
    # 2. XOR撹拌 (簡易暗号化)
    # bytesをbytearrayに変換して操作
    scrambled = bytearray(compressed_data)
    for i in range(len(scrambled)):
        scrambled[i] ^= password_int
    
    # 3. ヘッダー + データ
    return FILE_HEADER + scrambled

def custom_decompress(file_bytes: bytes, password_int: int) -> bytes:
    """
    1. ヘッダー確認
    2. XOR演算を逆に行う
    3. zlibで解凍
    """
    header_len = len(FILE_HEADER)
    
    # ヘッダーチェック
    if not file_bytes.startswith(FILE_HEADER):
        raise ValueError("このアプリで作成されたファイルではありません（ヘッダー不一致）。")
    
    # ヘッダーを除去
    scrambled_data = file_bytes[header_len:]
    
    # XOR逆変換
    unscrambled = bytearray(scrambled_data)
    for i in range(len(unscrambled)):
        unscrambled[i] ^= password_int
        
    # 解凍
    try:
        decompressed_data = zlib.decompress(unscrambled)
        return decompressed_data
    except zlib.error:
        raise ValueError("解凍に失敗しました。パスワード(Key)が間違っているか、データが破損しています。")

# --- Streamlit UI ---

st.set_page_config(page_title="独自形式コンプレッサー", layout="centered")

st.title("🗜️ 独自形式ファイル変換ツール")
st.markdown("""
このアプリは、標準的な解凍ソフトでは開けない**独自形式 (.myzip)** にファイルを圧縮・変換します。
内部で圧縮に加え、特定のキーを使ったビット演算を行っています。
""")

# サイドバー設定
st.sidebar.header("設定")
mode = st.sidebar.radio("モード選択", ["圧縮 (Compress)", "解凍 (Decompress)"])
secret_key = st.sidebar.slider("暗号化キー (0-255)", 0, 255, 123, help="この数字がパスワード代わりになります。解凍時にも同じ数字が必要です。")

st.divider()

if mode == "圧縮 (Compress)":
    st.subheader("ファイルの圧縮")
    uploaded_file = st.file_uploader("圧縮したいファイルをアップロード", type=None)

    if uploaded_file is not None:
        file_bytes = uploaded_file.read()
        file_name = uploaded_file.name
        
        if st.button("独自形式に変換して圧縮"):
            with st.spinner("処理中..."):
                try:
                    # 独自圧縮処理
                    processed_data = custom_compress(file_bytes, secret_key)
                    
                    st.success(f"圧縮成功！ サイズ: {len(file_bytes)}B -> {len(processed_data)}B")
                    
                    # ダウンロードボタン
                    st.download_button(
                        label="📦 .myzipファイルをダウンロード",
                        data=processed_data,
                        file_name=f"{file_name}.myzip",
                        mime="application/octet-stream"
                    )
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")

else:  # 解凍モード
    st.subheader("ファイルの解凍")
    uploaded_file = st.file_uploader("独自形式(.myzip)ファイルをアップロード", type=["myzip"])

    if uploaded_file is not None:
        file_bytes = uploaded_file.read()
        # 元のファイル名を推測（拡張子.myzipを取るだけの簡易実装）
        original_name = uploaded_file.name.replace(".myzip", "")
        if original_name == uploaded_file.name:
            original_name = "restored_file"

        if st.button("元のファイルに復元"):
            with st.spinner("解凍・復号中..."):
                try:
                    # 独自解凍処理
                    restored_data = custom_decompress(file_bytes, secret_key)
                    
                    st.success("復元成功！")
                    
                    # ダウンロードボタン
                    st.download_button(
                        label="📂 復元ファイルをダウンロード",
                        data=restored_data,
                        file_name=original_name,
                        mime="application/octet-stream"
                    )
                except ValueError as ve:
                    st.error(f"エラー: {ve}")
                except Exception as e:
                    st.error(f"予期せぬエラー: {e}")
