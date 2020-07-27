from flask import Request, Response, make_response

from slack_bolt.app import App
from slack_bolt.oauth.oauth_flow import OAuthFlow
from slack_bolt.request import BoltRequest
from slack_bolt.response import BoltResponse


def to_bolt_request(req: Request) -> BoltRequest:
    return BoltRequest(
        body=req.get_data(as_text=True),
        query=req.query_string.decode("utf-8"),
        headers=req.headers,
    )


def to_flask_response(bolt_resp: BoltResponse) -> Response:
    resp: Response = make_response(bolt_resp.body, bolt_resp.status)
    for k, values in bolt_resp.headers.items():
        for v in values:
            resp.headers.add_header(k, v)
    return resp


class SlackRequestHandler():
    def __init__(self, app: App):
        self.app = app

    def handle(self, req: Request) -> Response:
        if req.method == "GET":
            if self.app.oauth_flow is not None:
                oauth_flow: OAuthFlow = self.app.oauth_flow
                if req.path == self.app.oauth_flow.install_path:
                    bolt_resp = oauth_flow.handle_installation(to_bolt_request(req))
                    return to_flask_response(bolt_resp)
                elif req.path == self.app.oauth_flow.redirect_uri_path:
                    bolt_resp = oauth_flow.handle_callback(to_bolt_request(req))
                    return to_flask_response(bolt_resp)
        elif req.method == "POST":
            slack_req: BoltRequest = BoltRequest(
                body=req.get_data(as_text=True),
                headers={k.lower(): v for k, v in req.headers.items()}
            )
            bolt_resp: BoltResponse = self.app.dispatch(slack_req)
            resp: Response = make_response(bolt_resp.body, bolt_resp.status)
            for k, values in bolt_resp.headers.items():
                for v in values:
                    resp.headers.add_header(k, v)
            return resp

        return make_response("Not Found", 404)