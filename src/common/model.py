import logging

import litellm
from google.adk.models.lite_llm import LiteLlm

litellm.drop_params = True
litellm.set_verbose = False
litellm.suppress_debug_info = True

ll_logger = logging.getLogger("LiteLLM")

ll_logger.setLevel(logging.WARNING)
ll_logger.propagate = False

MODEL_NAME = "openai/gpt-5.4"
MODEL = LiteLlm(model=MODEL_NAME, temperature=0.7)

DUMMY_MODEL_NAME = "openai/gpt-4o"
DUMMY_MODEL = LiteLlm(model=DUMMY_MODEL_NAME, temperature=0.7)
