import numpy as np

from voice_call_agent.config import Vad
from voice_call_agent.contracts import AudioFrame
from voice_call_agent.vad import EndpointDetector


def frame(index):
    return AudioFrame(np.zeros(512, np.float32), index * 0.032)


def test_short_noise_does_not_trigger_barge_in():
    detector = EndpointDetector(Vad())
    assert not detector.feed(frame(0), 0.9).started
    assert not detector.feed(frame(1), 0.9).started
    assert not detector.feed(frame(2), 0.1).started
    assert not detector.active


def test_preroll_and_silence_endpoint_keep_the_start_of_the_word():
    detector = EndpointDetector(Vad())
    detector.feed(frame(0), 0.1)
    detector.feed(frame(1), 0.1)
    starts, utterances = [], []
    for i in range(2, 25):
        result = detector.feed(frame(i), 0.9 if i < 10 else 0.1)
        if result.started:
            starts.append(i)
        if result.utterance:
            utterances.append(result.utterance)
    assert starts == [4]
    assert len(utterances) == 1
    assert utterances[0].started_at == 0
    assert abs(utterances[0].speech_ended_at - 0.32) < 1e-8
    assert len(utterances[0].samples) == 25 * 512


def test_long_speech_is_bounded_and_reset_discards_incomplete_audio():
    detector = EndpointDetector(Vad(max_utterance_seconds=1))
    utterances = []
    for i in range(40):
        result = detector.feed(frame(i), 0.9)
        if result.utterance:
            utterances.append(result.utterance)
    assert len(utterances) == 1
    assert len(utterances[0].samples) <= 32 * 512
    detector.reset()
    assert not detector.active and not detector.frames
