"""A complete AnalysisResult built from the synthetic SEC data and a fake
Gemini, for testing the register, the report and the dashboard."""
from tests.sample_sec import FakeSession, standard_routes
from tests.test_llm_extractor import FakeGenerator
from tests.test_pipeline import AI_RESPONSE
from utils.pipeline import run_analysis
from utils.scoring import load_config
from utils.sec_client import SECClient


def sample_result(with_ai: bool = True):
    sec = SECClient(user_agent="Test Person test@example.com", session=FakeSession(standard_routes()),
                    cache_dir=None, sleep=lambda s: None)
    generate = FakeGenerator(AI_RESPONSE) if with_ai else None
    return run_analysis("EXMC", "10-K", sec, load_config(), generate)
