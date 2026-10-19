"""
Unit tests for the Extensible Subtitle Architecture:
1. CueParser (WebVTT & SRT parsing, normalization, and serialization)
2. TempSubtitleManager (lifecycle management and Section 16.4 'Xài xong dọn')
3. PlatformCaptionExtractor (YouTube & Facebook captions, YouTube TimedText tlang)
4. Pluggable AI Translator (OpenAI-compatible /v1/chat/completions and error fallback)
5. SubtitleDispatcher (Mutually exclusive 3-options selection: local, web, ai)
6. SettingsDialog Subtitle Tab 3-options integration and persistence
"""

import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from main.subtitle import (
    SubtitleCue,
    CueParser,
    TempSubtitleManager,
    PlatformCaptionExtractor,
    OpenAICompatibleTranslator,
    SubtitleDispatcher,
    validate_subtitle_file,
)
from main.settings import SettingsManager
from main.theme import ThemeManager
from main.gui import SettingsDialog


class TestCueParser(unittest.TestCase):
    """Test subtitle cue parsing and serialization."""

    def test_parse_and_serialize_vtt(self):
        vtt_content = (
            "WEBVTT\n\n"
            "1\n"
            "00:00:01.000 --> 00:00:04.000 align:start\n"
            "<v Speaker>Xin chào các bạn!</v>\n\n"
            "2\n"
            "00:00:05.500 --> 00:00:08.200\n"
            "Video xem mượt mà.\n"
        )
        cues = CueParser.parse_vtt(vtt_content)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].index, 1)
        self.assertEqual(cues[0].start, "00:00:01.000")
        self.assertEqual(cues[0].end, "00:00:04.000")
        self.assertEqual(cues[0].text, "Xin chào các bạn!")
        self.assertEqual(cues[0].settings, "align:start")

        self.assertEqual(cues[1].index, 2)
        self.assertEqual(cues[1].start, "00:00:05.500")
        self.assertEqual(cues[1].text, "Video xem mượt mà.")

        # Serialize back
        serialized = CueParser.serialize_vtt(cues)
        self.assertIn("WEBVTT", serialized)
        self.assertIn("00:00:01.000 --> 00:00:04.000 align:start", serialized)
        self.assertIn("Xin chào các bạn!", serialized)

    def test_parse_and_serialize_srt(self):
        srt_content = (
            "1\n"
            "00:00:02,100 --> 00:00:05,300\n"
            "SubRip line 1\n\n"
            "2\n"
            "00:00:06,000 --> 00:00:09,000\n"
            "SubRip line 2\n"
        )
        cues = CueParser.parse_srt(srt_content)
        self.assertEqual(len(cues), 2)
        # Verify comma normalized to dot in SubtitleCue
        self.assertEqual(cues[0].start, "00:00:02.100")
        self.assertEqual(cues[0].end, "00:00:05.300")
        self.assertEqual(cues[0].text, "SubRip line 1")


class TestTempSubtitleManager(unittest.TestCase):
    """Test Section 16.4 'Xài xong dọn' lifecycle management."""

    def setUp(self):
        self.mgr = TempSubtitleManager.get_instance()

    def test_save_and_cleanup(self):
        vid = "test_video_123"
        content = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nHello\n"
        path = self.mgr.save_temp_subtitle(video_id=vid, content=content, ext=".vtt", tag="web")
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(encoding="utf-8"), content)

        # Cleanup video
        self.mgr.cleanup_video(vid)
        self.assertFalse(path.exists())

    def test_auto_cleanup_previous_active_file(self):
        path1 = self.mgr.save_temp_subtitle("vid_a", "WEBVTT\n1\n00:01.000 --> 00:02.000\nA\n")
        self.assertTrue(path1.exists())

        # Saving second file must clean up path1 automatically
        path2 = self.mgr.save_temp_subtitle("vid_b", "WEBVTT\n1\n00:01.000 --> 00:02.000\nB\n")
        self.assertTrue(path2.exists())
        self.assertFalse(path1.exists())

        # Cleanup all
        self.mgr.cleanup_all()
        self.assertFalse(path2.exists())


class TestPlatformCaptionExtractor(unittest.TestCase):
    """Test YouTube and Facebook caption extraction logic."""

    def test_youtube_creator_subtitle_match(self):
        info_dict = {
            "subtitles": {
                "vi": [{"ext": "vtt", "url": "https://example.com/vi.vtt"}],
                "en": [{"ext": "vtt", "url": "https://example.com/en.vtt"}],
            },
            "automatic_captions": {},
        }
        url = PlatformCaptionExtractor.extract_youtube_caption_url(
            info_dict, prefer_original=True, auto_translate=True, target_lang="vi"
        )
        self.assertEqual(url, "https://example.com/vi.vtt")

    def test_youtube_native_timedtext_auto_translation(self):
        info_dict = {
            "subtitles": {},
            "automatic_captions": {
                "en": [{"ext": "vtt", "url": "https://www.youtube.com/api/timedtext?v=abc&lang=en&fmt=vtt"}],
            },
        }
        url = PlatformCaptionExtractor.extract_youtube_caption_url(
            info_dict, prefer_original=True, auto_translate=True, target_lang="vi"
        )
        self.assertIsNotNone(url)
        self.assertIn("tlang=vi", url)
        self.assertIn("fmt=vtt", url)

    def test_facebook_caption_extraction(self):
        info_dict = {
            "subtitles": {
                "vi": [{"ext": "vtt", "url": "https://facebook.com/sub_vi.vtt"}],
            }
        }
        url = PlatformCaptionExtractor.extract_facebook_caption_url(
            info_dict, prefer_original=True, target_lang="vi"
        )
        self.assertEqual(url, "https://facebook.com/sub_vi.vtt")


class TestOpenAICompatibleTranslator(unittest.TestCase):
    """Test AI translation interface with mocked OpenAI API completion."""

    @patch("urllib.request.urlopen")
    def test_translate_cues_success(self, mock_urlopen):
        mock_response = MagicMock()
        mock_payload = {
            "choices": [
                {
                    "message": {
                        "content": "[1] Xin chào thế giới\n[2] Bạn khỏe không?"
                    }
                }
            ]
        }
        mock_response.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        translator = OpenAICompatibleTranslator(
            endpoint="https://api.openai.com/v1",
            api_key="test_key",
            model="gpt-4o-mini",
        )

        cues = [
            SubtitleCue(1, "00:00:01.000", "00:00:04.000", "Hello world"),
            SubtitleCue(2, "00:00:05.000", "00:00:08.000", "How are you?"),
        ]

        translated = translator.translate_cues(cues, target_lang="vi")
        self.assertEqual(len(translated), 2)
        self.assertEqual(translated[0].text, "Xin chào thế giới")
        self.assertEqual(translated[1].text, "Bạn khỏe không?")
        # Check timestamps preserved
        self.assertEqual(translated[0].start, "00:00:01.000")
        self.assertEqual(translated[1].end, "00:00:08.000")

    @patch("urllib.request.urlopen")
    def test_translate_cues_error_fallback(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Network Connection Refused")

        translator = OpenAICompatibleTranslator(
            endpoint="https://api.openai.com/v1",
            api_key="test_key",
            model="gpt-4o-mini",
        )

        cues = [
            SubtitleCue(1, "00:00:01.000", "00:00:04.000", "Hello world"),
        ]

        # Fail-safe: must fallback to original text rather than crash
        translated = translator.translate_cues(cues, target_lang="vi")
        self.assertEqual(len(translated), 1)
        self.assertEqual(translated[0].text, "Hello world")


class TestSubtitleDispatcher(unittest.TestCase):
    """Test mutually exclusive 3-options dispatcher logic."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()
        TempSubtitleManager.get_instance().cleanup_all()

    def test_disabled_returns_none(self):
        res = SubtitleDispatcher.resolve_subtitle_for_stream(
            video_url="https://youtube.com/watch?v=123",
            info_dict={},
            sub_settings={"enabled": False, "source_option": "web"},
        )
        self.assertIsNone(res)

    def test_option_1_local_file(self):
        sub_file = self.dir_path / "valid.srt"
        sub_file.write_text("1\n00:00:01,000 --> 00:00:04,000\nHello\n", encoding="utf-8")

        res = SubtitleDispatcher.resolve_subtitle_for_stream(
            video_url="https://youtube.com/watch?v=123",
            info_dict={},
            sub_settings={
                "enabled": True,
                "source_option": "local",
                "local_file": str(sub_file),
            },
        )
        self.assertEqual(res, str(sub_file.resolve()))

    @patch.object(PlatformCaptionExtractor, "download_caption")
    def test_option_2_web_captions(self, mock_dl):
        mock_sub = self.dir_path / "mock_web.vtt"
        mock_sub.write_text("WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nWeb Sub\n", encoding="utf-8")
        mock_dl.return_value = mock_sub

        info_dict = {
            "id": "yt_video_1",
            "subtitles": {
                "vi": [{"ext": "vtt", "url": "https://example.com/vi.vtt"}],
            },
        }

        res = SubtitleDispatcher.resolve_subtitle_for_stream(
            video_url="https://www.youtube.com/watch?v=yt_video_1",
            info_dict=info_dict,
            sub_settings={
                "enabled": True,
                "source_option": "web",
                "web_captions": {
                    "youtube_prefer_original": True,
                    "target_lang": "vi",
                },
            },
        )
        self.assertEqual(res, str(mock_sub.resolve()))


class TestSettingsDialogSubtitleTab(unittest.TestCase):
    """Test SettingsDialog subtitle tab UI and 3-options switching."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.settings_dir = Path(self.temp_dir.name)
        self.settings = SettingsManager(config_dir=self.settings_dir)
        self.theme = ThemeManager(self.root, "dark")

    def tearDown(self):
        self.root.destroy()
        self.temp_dir.cleanup()

    def test_settings_dialog_subtitle_tab_options(self):
        dialog = SettingsDialog(self.root, self.settings, self.theme, initial_tab="subtitles")

        # Verify initial variables initialized
        self.assertTrue(hasattr(dialog, "sub_enabled_var"))
        self.assertTrue(hasattr(dialog, "sub_source_option_var"))
        self.assertTrue(hasattr(dialog, "sub_yt_prefer_orig_var"))
        self.assertTrue(hasattr(dialog, "sub_ai_endpoint_var"))

        # Test switching between 3 options
        dialog.sub_source_option_var.set("local")
        dialog._on_sub_source_changed()
        self.assertEqual(dialog.frame_opt_local.winfo_manager(), "pack")
        self.assertEqual(dialog.frame_opt_web.winfo_manager(), "")
        self.assertEqual(dialog.frame_opt_ai.winfo_manager(), "")

        dialog.sub_source_option_var.set("web")
        dialog._on_sub_source_changed()
        self.assertEqual(dialog.frame_opt_local.winfo_manager(), "")
        self.assertEqual(dialog.frame_opt_web.winfo_manager(), "pack")
        self.assertEqual(dialog.frame_opt_ai.winfo_manager(), "")

        dialog.sub_source_option_var.set("ai")
        dialog._on_sub_source_changed()
        self.assertEqual(dialog.frame_opt_local.winfo_manager(), "")
        self.assertEqual(dialog.frame_opt_web.winfo_manager(), "")
        self.assertEqual(dialog.frame_opt_ai.winfo_manager(), "pack")

        # Test toggle show/hide AI key
        dialog._toggle_show_ai_api_key()
        self.assertEqual(dialog.entry_ai_key.cget("show"), "")
        dialog._toggle_show_ai_api_key()
        self.assertEqual(dialog.entry_ai_key.cget("show"), "*")

        dialog.top.destroy()


if __name__ == "__main__":
    unittest.main()
