"""Deterministic tests for structure-aware chunking (no embeddings)."""

from django.test import SimpleTestCase, override_settings

from apps.knowledge.pipeline.chunk import chunk_pages
from apps.knowledge.pipeline.chunk_blocks import BlockKind, build_blocks
from apps.knowledge.pipeline.chunk_sentences import split_sentences
from apps.knowledge.pipeline.extract import PageText


@override_settings(
    KNOWLEDGE_CHUNK_SIZE=120,
    KNOWLEDGE_CHUNK_OVERLAP=40,
    KNOWLEDGE_CHUNK_MIN_CHARS=10,
)
class ChunkingTests(SimpleTestCase):
    def test_heading_inherited_by_following_paragraph(self):
        pages = [
            PageText(
                1,
                "INSURANCE\n\nWe accept Blue Cross PPO Gold and Aetna HMO Plus.",
            )
        ]
        chunks = chunk_pages(pages)
        self.assertTrue(chunks)
        self.assertEqual(chunks[0].heading, "INSURANCE")
        self.assertIn("Blue Cross", chunks[0].content)

    def test_list_stays_together(self):
        pages = [
            PageText(
                1,
                "Bring to visit\n\n"
                "- Insurance card\n"
                "- Photo ID\n"
                "- Medication list",
            )
        ]
        chunks = chunk_pages(pages)
        joined = "\n\n".join(c.content for c in chunks)
        # List items must remain contiguous (not split across chunks)
        self.assertIn(
            "- Insurance card\n- Photo ID\n- Medication list",
            joined,
        )

    def test_cross_page_paragraph(self):
        pages = [
            PageText(1, "Patients should arrive fifteen minutes early and"),
            PageText(2, "bring their insurance card to every appointment."),
        ]
        blocks = build_blocks(pages)
        paras = [b for b in blocks if b.kind.value == "paragraph"]
        self.assertTrue(paras)
        self.assertEqual(paras[0].page_start, 1)
        self.assertEqual(paras[0].page_end, 2)
        self.assertIn("insurance card", paras[0].text)

    def test_sentence_split_does_not_cut_abbreviation(self):
        text = "See Dr. Sharma for follow-up. Bring labs."
        sentences = split_sentences(text)
        self.assertEqual(len(sentences), 2)
        self.assertTrue(sentences[0].startswith("See Dr."))

    def test_page_number_noise_dropped(self):
        pages = [
            PageText(1, "Clinic hours are 8am to 6pm.\n\n2\n"),
            PageText(2, "Page 2 of 2\n\nWe are closed on Sundays."),
        ]
        chunks = chunk_pages(pages)
        joined = " ".join(c.content for c in chunks)
        self.assertNotIn("Page 2 of 2", joined)
        self.assertIn("closed on Sundays", joined)


class AcademicPaperHeadingTests(SimpleTestCase):
    """Research-paper heading detection: real sections vs table/author noise."""

    def _heading_texts(self, text: str) -> list[str]:
        pages = [PageText(1, text)]
        return [b.text for b in build_blocks(pages) if b.kind == BlockKind.HEADING]

    def test_real_section_headings_detected(self):
        paper = (
            "Abstract\n\n"
            "We propose a new method.\n\n"
            "1 Introduction\n\n"
            "Large language models are useful.\n\n"
            "2 Related Work\n\n"
            "Prior work explored retrieval.\n\n"
            "3.2 Chunking-Free Architecture\n\n"
            "Our design avoids chunking.\n\n"
            "4 Experiment\n\n"
            "We evaluate on benchmarks.\n\n"
            "5 Conclusion\n\n"
            "We summarize findings.\n\n"
            "References\n\n"
            "Tianqi Chen, Bing Xu, Alice Brown\n"
            "Pradeep Dasigi, John Smith\n"
        )
        headings = self._heading_texts(paper)
        self.assertIn("Abstract", headings)
        self.assertIn("Introduction", headings)
        self.assertIn("Related Work", headings)
        self.assertIn("Chunking-Free Architecture", headings)
        self.assertIn("Experiment", headings)
        self.assertIn("Conclusion", headings)
        self.assertIn("References", headings)

    def test_table_and_author_lines_not_headings(self):
        paper = (
            "4 Experiment\n\n"
            "LE1 LEi LEn\n"
            "SE1\n"
            "SE3 LE3\n"
            "Stage III. 40K 30K 10K 10K 90K\n"
            "Llama2-7B-chat\n"
            "ChatGPT-3.5-turbo\n"
            "Dataset Doc Len. Method MRR@10 Recall@10\n"
            "Qasper, MultifieldQA, 2WikiMQA, HotpotQA\n"
            "88.3 91.5 79.4\n"
            "Table 1: Main results\n"
            "Figure 2. Ablation study\n"
            "Learning\n\n"
            "This paragraph discusses transfer learning in depth and "
            "should not be split under a spurious heading.\n\n"
            "References\n\n"
            "Tianqi Chen, Bing Xu, Alice Brown\n"
            "Pradeep Dasigi...\n"
            "Albert Q. Jiang, Alexandre Sablayrolles\n"
        )
        headings = self._heading_texts(paper)
        self.assertEqual(headings, ["Experiment", "References"])

    def test_no_headings_after_references_section(self):
        paper = (
            "References\n\n"
            "Tianqi Chen, Bing Xu\n"
            "Pradeep Dasigi\n"
            "5 Conclusion\n"
            "Appendix\n"
        )
        headings = self._heading_texts(paper)
        self.assertEqual(headings, ["References"])

    def test_markdown_headings_still_work(self):
        paper = "## Methods\n\nWe used a controlled trial.\n\n### Results\n\nOutcomes improved."
        headings = self._heading_texts(paper)
        self.assertIn("Methods", headings)
        self.assertIn("Results", headings)
