import unittest

from aiohttp import web
from aiohttp.test_utils import TestServer

from momoi.models import ToolCall
from momoi.tools.builtin import BuiltinTools
from momoi.tools.web_fetch import MAX_RESPONSE_BYTES


class WebFetchTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.methods = []

        async def endpoint(request):
            self.methods.append(request.method)
            match request.path:
                case "/redirect":
                    raise web.HTTPFound("/page")
                case "/page":
                    return web.Response(text='''<html><head><title>测试 page</title>
                        <style>secret-style</style></head><body><h1>Hello 世界</h1>
                        <p>Read <a href="/next">next</a> &amp; enjoy.</p>
                        <script>secret-script</script><div hidden>secret-hidden</div>
                        <a href="javascript:alert(1)">unsafe link</a></body></html>''', content_type="text/html")
                case "/json":
                    return web.json_response({"hello": "world"})
                case "/large":
                    return web.Response(text="x" * (MAX_RESPONSE_BYTES + 1))
                case "/binary":
                    return web.Response(body=b"\x00\x01", content_type="image/png")
                case "/error":
                    return web.Response(status=404, text="missing")
                case "/slow":
                    import asyncio
                    await asyncio.sleep(0.2)
                    return web.Response(text="late")
                case _:
                    return web.Response(body=b"caf\xe9", headers={"Content-Type": "text/plain; charset=iso-8859-1"})

        app = web.Application()
        app.router.add_route("*", "/{path:.*}", endpoint)
        self.server = TestServer(app)
        await self.server.start_server()
        self.addAsyncCleanup(self.server.close)
        self.tools = BuiltinTools()

    async def fetch(self, path, **arguments):
        return await self.tools.execute(ToolCall("fetch", "web_fetch", {
            "url": str(self.server.make_url(path)), **arguments,
        }))

    async def test_html_markdown_text_title_and_redirect(self):
        result = await self.fetch("/redirect")
        self.assertTrue(result["ok"])
        self.assertEqual(result["title"], "测试 page")
        self.assertTrue(result["url"].endswith("/page"))
        self.assertTrue(result["requested_url"].endswith("/redirect"))
        self.assertIn("# Hello 世界", result["content"])
        self.assertIn(f'[next]({self.server.make_url("/next")})', result["content"])
        self.assertNotIn("secret-", result["content"])
        self.assertNotIn("javascript:", result["content"])
        self.assertFalse(result["truncated"])
        plain = await self.fetch("/page", extract_mode="text")
        self.assertIn("Hello 世界", plain["content"])
        self.assertNotIn("# ", plain["content"])
        self.assertNotIn("[next]", plain["content"])
        self.assertEqual(set(self.methods), {"GET"})

    async def test_text_json_errors_and_encoding(self):
        result = await self.fetch("/json")
        self.assertEqual(result["content"], '{"hello": "world"}')
        self.assertEqual(result["content_type"], "application/json")
        self.assertEqual((await self.fetch("/latin"))["content"], "café")
        result = await self.fetch("/error")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 404)
        self.assertEqual(result["error"], "http_error")
        self.assertEqual(result["content"], "missing")
        self.assertEqual((await self.fetch("/binary"))["error"], "unsupported_content_type")
        self.assertFalse((await self.fetch("/slow", timeout_seconds=0.1))["ok"])

    async def test_source_and_extracted_content_limits(self):
        result = await self.fetch("/large", max_chars=13)
        self.assertEqual(result["content"], "x" * 13)
        self.assertTrue(result["source_truncated"])
        self.assertTrue(result["truncated"])
        self.assertEqual(result["content_length"], MAX_RESPONSE_BYTES)
        result = await self.fetch("/page", max_chars=5)
        self.assertEqual(len(result["content"]), 5)
        self.assertFalse(result["source_truncated"])
        self.assertTrue(result["truncated"])

    async def test_invalid_arguments_and_old_tool_never_send_requests(self):
        for arguments in (
            {"method": "POST"}, {"body": "data"}, {"extract_mode": "raw"},
            {"max_chars": True}, {"max_chars": 0}, {"max_chars": 200001},
            {"timeout_seconds": float("nan")}, {"timeout_seconds": True},
        ):
            self.assertFalse((await self.fetch("/page", **arguments))["ok"])
        for url in ("file:///tmp/file", "ftp://example.com", "https://"):
            result = await self.tools.execute(ToolCall("invalid", "web_fetch", {"url": url}))
            self.assertFalse(result["ok"])
        self.assertFalse(self.tools.has_tool("curl"))
        self.assertEqual((await self.tools.execute(ToolCall("old", "curl", {})))["error"], "tool_not_allowed")
        self.assertEqual(self.methods, [])
