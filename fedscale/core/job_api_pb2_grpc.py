# Generated by the gRPC Python protocol compiler plugin. DO NOT EDIT!
"""Client and server classes corresponding to protobuf-defined services."""
import grpc

import fedscale.core.job_api_pb2 as job__api__pb2


class JobServiceStub(object):
    """Missing associated documentation comment in .proto file."""

    def __init__(self, channel):
        """Constructor.

        Args:
            channel: A grpc.Channel.
        """
        self.CLIENT_REGISTER = channel.unary_unary(
                '/fedscale.JobService/CLIENT_REGISTER',
                request_serializer=job__api__pb2.RegisterRequest.SerializeToString,
                response_deserializer=job__api__pb2.ServerResponse.FromString,
                )
        self.CLIENT_PING = channel.unary_unary(
                '/fedscale.JobService/CLIENT_PING',
                request_serializer=job__api__pb2.PingRequest.SerializeToString,
                response_deserializer=job__api__pb2.ServerResponse.FromString,
                )
        self.CLIENT_EXECUTE_COMPLETION = channel.unary_unary(
                '/fedscale.JobService/CLIENT_EXECUTE_COMPLETION',
                request_serializer=job__api__pb2.CompleteRequest.SerializeToString,
                response_deserializer=job__api__pb2.ServerResponse.FromString,
                )


class JobServiceServicer(object):
    """Missing associated documentation comment in .proto file."""

    def CLIENT_REGISTER(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def CLIENT_PING(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')

    def CLIENT_EXECUTE_COMPLETION(self, request, context):
        """Missing associated documentation comment in .proto file."""
        context.set_code(grpc.StatusCode.UNIMPLEMENTED)
        context.set_details('Method not implemented!')
        raise NotImplementedError('Method not implemented!')


def add_JobServiceServicer_to_server(servicer, server):
    rpc_method_handlers = {
            'CLIENT_REGISTER': grpc.unary_unary_rpc_method_handler(
                    servicer.CLIENT_REGISTER,
                    request_deserializer=job__api__pb2.RegisterRequest.FromString,
                    response_serializer=job__api__pb2.ServerResponse.SerializeToString,
            ),
            'CLIENT_PING': grpc.unary_unary_rpc_method_handler(
                    servicer.CLIENT_PING,
                    request_deserializer=job__api__pb2.PingRequest.FromString,
                    response_serializer=job__api__pb2.ServerResponse.SerializeToString,
            ),
            'CLIENT_EXECUTE_COMPLETION': grpc.unary_unary_rpc_method_handler(
                    servicer.CLIENT_EXECUTE_COMPLETION,
                    request_deserializer=job__api__pb2.CompleteRequest.FromString,
                    response_serializer=job__api__pb2.ServerResponse.SerializeToString,
            ),
    }
    generic_handler = grpc.method_handlers_generic_handler(
            'fedscale.JobService', rpc_method_handlers)
    server.add_generic_rpc_handlers((generic_handler,))


 # This class is part of an EXPERIMENTAL API.
class JobService(object):
    """Missing associated documentation comment in .proto file."""

    @staticmethod
    def CLIENT_REGISTER(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(request, target, '/fedscale.JobService/CLIENT_REGISTER',
            job__api__pb2.RegisterRequest.SerializeToString,
            job__api__pb2.ServerResponse.FromString,
            options, channel_credentials,
            insecure, call_credentials, compression, wait_for_ready, timeout, metadata)

    @staticmethod
    def CLIENT_PING(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(request, target, '/fedscale.JobService/CLIENT_PING',
            job__api__pb2.PingRequest.SerializeToString,
            job__api__pb2.ServerResponse.FromString,
            options, channel_credentials,
            insecure, call_credentials, compression, wait_for_ready, timeout, metadata)

    @staticmethod
    def CLIENT_EXECUTE_COMPLETION(request,
            target,
            options=(),
            channel_credentials=None,
            call_credentials=None,
            insecure=False,
            compression=None,
            wait_for_ready=None,
            timeout=None,
            metadata=None):
        return grpc.experimental.unary_unary(request, target, '/fedscale.JobService/CLIENT_EXECUTE_COMPLETION',
            job__api__pb2.CompleteRequest.SerializeToString,
            job__api__pb2.ServerResponse.FromString,
            options, channel_credentials,
            insecure, call_credentials, compression, wait_for_ready, timeout, metadata)
