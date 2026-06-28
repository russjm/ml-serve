import os
from dataclasses import dataclass

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

DEFAULT_MODEL = "distilbert-base-uncased-finetuned-sst-2-english"
MAX_TOKENS = 256


@dataclass
class Prediction:
    label: str
    score: float


class ModelRunner:
    def __init__(self, model_name_or_path=None):
        model_name_or_path = model_name_or_path or os.environ.get("MODEL_PATH", DEFAULT_MODEL)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name_or_path)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name_or_path)
        self.model.eval()
        self.device = torch.device("cpu")
        self.model.to(self.device)
        self.id2label = self.model.config.id2label

    @torch.inference_mode()
    def forward(self, texts: list[str]) -> list[Prediction]:
        enc = self.tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=MAX_TOKENS,
            return_tensors="pt",
        ).to(self.device)
        logits = self.model(**enc).logits
        probs = torch.softmax(logits, dim=-1)
        scores, idx = probs.max(dim=-1)
        return [
            Prediction(label=self.id2label[i.item()], score=float(s))
            for i, s in zip(idx, scores)
        ]
