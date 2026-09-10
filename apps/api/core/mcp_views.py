"""HTTP boundary, deliberately separate from inference and human administration."""

from io import BytesIO

from rest_framework.authentication import BaseAuthentication, SessionAuthentication
from rest_framework.exceptions import APIException, ParseError
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.audit import record_audit
from core.mcp_boundary import authenticate_machine, call_tool, mint_delegation


class BoundedJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        data = stream.read(16385)
        if len(data) > 16384:
            raise ParseError("Chamada MCP excede o limite de 16 KiB.")
        return super().parse(
            BytesIO(data), media_type=media_type, parser_context=parser_context
        )


class MachineAuthentication(BaseAuthentication):
    def authenticate(self, request):
        return authenticate_machine(request.headers.get("Authorization", ""))

    def authenticate_header(self, request):
        return "Bearer"


class MCPDelegationView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [BoundedJSONParser]

    def post(self, request):
        try:
            result = mint_delegation(request, request.data)
        except APIException as exc:
            record_audit(
                "mcp.delegation.denied",
                actor=request.user,
                request=request,
                metadata={"status": exc.status_code},
            )
            raise
        return Response(result, headers={"Cache-Control": "no-store"})


class MCPToolCallView(APIView):
    authentication_classes = [MachineAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [BoundedJSONParser]

    def post(self, request):
        try:
            result = call_tool(request, request.data)
        except APIException as exc:
            record_audit(
                "mcp.tool.denied",
                actor=request.user,
                request=request,
                metadata={"status": exc.status_code},
            )
            raise
        return Response(result, headers={"Cache-Control": "no-store"})
