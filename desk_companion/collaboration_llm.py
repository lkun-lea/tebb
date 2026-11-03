"""Product policies for collaboration; Atlas owns transport and stream assembly."""
from atlas.llm import ChatCallbacks, ChatOptions
from openai import OpenAI
from .execution_context import ExecutionLLM


class ConfigurationChanged(ValueError):
    public_message='模型、容量或输出配置已变化；未发送。请重新预览后发送目标。'


class CollaborationLLM:
    def __init__(self, model, sampling, timeout, client=None, purpose='task',expected_configuration_revision=None):
        self.model = model
        self.sampling = {**sampling, **({'reasoning_effort': 'low'} if purpose == 'route' else {})}
        self.preserve_reasoning = model['model'].lower().startswith(('glm-4.7', 'glm-5'))
        self.timeout = timeout
        self.client = client
        self.owned = client is None
        self._llm = None
        self.on_reasoning = None
        self.on_progress = None
        self.on_tool_delta = None
        self.on_context = None
        self.expected_configuration_revision=expected_configuration_revision

    def __enter__(self): return self

    def __exit__(self, *args): self.close()

    def close(self):
        if self._llm is not None:
            self._llm.close()
            self._llm = None
        if self.owned and self.client is not None:
            self.client.close()
            self.client = None

    def chat(self, messages, tools=None, on_delta=None, *, should_cancel=None):
        from .review_limits import current_window,ReviewTimeout
        review=current_window()
        if review:review.check()
        if self.expected_configuration_revision:
            from .execution_context import configuration_revision
            from .model_catalog import require_item
            if configuration_revision(require_item(self.model['id']))!=self.expected_configuration_revision:
                raise ConfigurationChanged(ConfigurationChanged.public_message)
        if self._llm is None:
            if self.client is None:
                from .model_network import http_client
                self.client = http_client(self.timeout)
            sdk = OpenAI(api_key=self.model['api_key'], base_url=self.model['base_url'],
                         timeout=self.client.timeout, max_retries=0, http_client=self.client)
            self._llm = ExecutionLLM(model=self.model['model'],client=sdk,context_model_id=self.model.get('id',''),
                                     on_context=lambda report:self.on_context(report)if self.on_context else None)
        extra = {'thinking': {'clear_thinking': False}, 'tool_stream': True} if self.preserve_reasoning else None
        try:
            driver=self._llm;client=driver.client
            if review:driver.bind_client(client.with_options(timeout=min(self.timeout,review.remaining())))
            try:
                return driver.chat(messages, tools, options=ChatOptions(
                    sampling={k:v for k,v in self.sampling.items()if k!='reasoning_effort'}if review else self.sampling,
                    extra_body=extra, stream=True,preserve_reasoning=self.preserve_reasoning,
                    should_cancel=(lambda:review.expired()or bool(should_cancel and should_cancel()))if review else should_cancel,
                ), callbacks=ChatCallbacks(on_delta=on_delta, on_reasoning=self.on_reasoning,
                    on_progress=self.on_progress, on_tool_delta=self.on_tool_delta))
            finally:
                if review:driver.bind_client(client)
        except Exception as exc:
            self.close()
            if review and review.expired():raise ReviewTimeout('独立审阅时间窗口已到，候选和实际回执保留，未算验收通过。')from exc
            raise
