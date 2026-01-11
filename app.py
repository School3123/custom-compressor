import streamlit as st
import lzma
import struct
import io
import os

# --- 設定 ---
# 独自のファイル識別子 (Magic Number)
MAGIC_NUMBER = b'MYCP'
# バージョン (将来の拡張用)
VERSION = 1

def compress_data(file_bytes, original_filename):
    """
    データをLZMA(最高圧縮)で圧縮し、独自ヘッダーを付与する
    フォーマット: [MAGIC(4)] [VERSION(1)] [FilenameLen(2)] [Filename(N)] [CompressedData]
    """
    try:
        # ファイル名をバイト列に変換
        filename_bytes = original_filename.encode('utf-8')
        filename_len = len(filename_bytes)

        # ヘッダー作成
        # I: Magic(4bytes, intとして処理も可だがここは生バイト)
        # B: Version(1byte)
        # H: Filename Length(2bytes, unsigned short. max 65535)
        header = MAGIC_NUMBER + struct.pack('>B H', VERSION, filename_len) + filename_bytes

        # 最高圧縮率(preset=9)で圧縮
        # extreme=Trueでさらに圧縮率を稼ぐ（時間はかかる）
        compressed_body = lzma.compress(file_bytes, preset=9 | lzma.PRESET_EXTREME)

        return header + compressed_body
    except Exception as e:
        st.error(f"圧縮エラー: {e}")
        return None

def decompress_data(file_bytes):
    """
    独自形式のファイルを解析し、元のファイル名とデータを復元する
    """
    try:
        cursor = 0
        
        # 1. マジックナンバー確認
        magic = file_bytes[cursor:cursor+4]
        cursor += 4
        if magic != MAGIC_NUMBER:
            st.error("エラー: このアプリで作成されたファイルではありません (Invalid Magic Number)。")
            return None, None

        # 2. バージョンとファイル名長を取得
        # >B H: Big-endian, unsigned char, unsigned short
        version, filename_len = struct.unpack('>B H', file_bytes[cursor:cursor+3])
        cursor += 3

        # 3. 元のファイル名を取得
        filename_bytes = file_bytes[cursor:cursor+filename_len]
        original_filename = filename_bytes.decode('utf-8')
        cursor += filename_len

        # 4. 解凍
        compressed_body = file_bytes[cursor:]
        decompressed_data = lzma.decompress(compressed_body)

        return original_filename, decompressed_data

    except Exception as e:
        st.error(f"解凍エラー: データが破損している可能性があります。\n詳細: {e}")
        return None, None

# --- UI構築 (Streamlit) ---
st.set_page_config(page_title="Ultra Compress App", layout="centered")

st.title("🗜️ Ultra Compression & Custom Container")
st.markdown("""
GitHub Codespacesで動作する独自圧縮アプリです。
Python標準で最も圧縮率の高い **LZMA (Preset 9/Extreme)** を使用し、
独自の `.mycmp` コンテナにファイル名を保持して格納します。
""")

tab1, tab2 = st.tabs(["圧縮 (Compress)", "解凍 (Decompress)"])

# --- 圧縮タブ ---
with tab1:
    st.header("ファイルをアップロードして圧縮")
    uploaded_file = st.file_uploader("任意のファイルを選択", key="compress_uploader")

    if uploaded_file is not None:
        file_bytes = uploaded_file.getvalue()
        file_name = uploaded_file.name
        original_size = len(file_bytes)

        if st.button("圧縮開始", key="compress_btn"):
            with st.spinner('最高設定で圧縮中... (大きなファイルは時間がかかります)'):
                compressed_data = compress_data(file_bytes, file_name)
            
            if compressed_data:
                compressed_size = len(compressed_data)
                ratio = (1 - (compressed_size / original_size)) * 100
                
                st.success("圧縮完了！")
                col1, col2, col3 = st.columns(3)
                col1.metric("元サイズ", f"{original_size:,} bytes")
                col2.metric("圧縮後サイズ", f"{compressed_size:,} bytes")
                col3.metric("削減率", f"{ratio:.2f}%")

                # ダウンロードボタン
                st.download_button(
                    label="圧縮ファイルをダウンロード (.mycmp)",
                    data=compressed_data,
                    file_name=f"{file_name}.mycmp",
                    mime="application/octet-stream"
                )

# --- 解凍タブ ---
with tab2:
    st.header("独自形式 (.mycmp) を解凍")
    uploaded_mycmp = st.file_uploader("圧縮ファイル (.mycmp) を選択", type=["mycmp"], key="decompress_uploader")

    if uploaded_mycmp is not None:
        if st.button("解凍開始", key="decompress_btn"):
            with st.spinner('解凍中...'):
                orig_name, dec_data = decompress_data(uploaded_mycmp.getvalue())
            
            if orig_name and dec_data:
                st.success(f"復元成功: {orig_name}")
                
                st.download_button(
                    label=f"解凍されたファイルをダウンロード ({orig_name})",
                    data=dec_data,
                    file_name=orig_name,
                    mime="application/octet-stream"
                )
