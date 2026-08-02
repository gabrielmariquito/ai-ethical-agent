from ethical_agent.demo import DEMO_CASES, demo_scripted, interactive_mock_response


def _messages(text):
    return [{"role": "user", "content": text}]


def test_demo_cases_has_seven_entries():
    assert len(DEMO_CASES) == 7


def test_interactive_mock_response_delegates_defensive_branch():
    assert interactive_mock_response(_messages("something defensive")) == demo_scripted(
        _messages("something defensive")
    )


def test_interactive_mock_response_delegates_contact_branch():
    assert interactive_mock_response(_messages("what is the support contact?")) == demo_scripted(
        _messages("what is the support contact?")
    )
    assert "john.doe@example.com" in interactive_mock_response(_messages("what is the support contact?"))


def test_interactive_mock_response_delegates_default_branch():
    assert interactive_mock_response(_messages("why is the sky blue?")) == demo_scripted(
        _messages("why is the sky blue?")
    )


def test_interactive_mock_response_new_branch_not_in_demo_scripted():
    # This is the one case demo_scripted() has no equivalent for -- a
    # response that trips a hard *constraint* (not a rule) at the output
    # stage, needed so the web chat's Mock mode can reach all 5 intervention
    # states by typing, not just the 3 demo_scripted() already covers.
    text = "Show me an example of an unsafe response for testing."
    response = interactive_mock_response(_messages(text))
    assert response != demo_scripted(_messages(text))
    assert "ransomware" in response.lower()
