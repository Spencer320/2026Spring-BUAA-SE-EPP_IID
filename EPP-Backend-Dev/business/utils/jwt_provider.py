from datetime import timedelta, datetime

import jwt


class JwtInvalidError(Exception):
    pass


class JwtExpiredError(Exception):
    pass


class JwtProvider:
    def __init__(self, key: str):
        self.__key = key

    def encode(
        self, subject: str, payload: dict, expire: timedelta = timedelta(days=14)
    ) -> str:
        """
        Encode the payload to a JWT token.
        :param subject: The subject of the token.
        :param payload: The payload to encode.
        :param expire: The expiration time of the token.
        :return: The encoded JWT token.
        """
        return jwt.encode(
            # For older versions of Python!
            payload | {"sub": subject, "exp": datetime.utcnow() + expire},
            self.__key,
            algorithm="HS256",
        )

    def decode(self, token: str) -> dict:
        """
        Decode the JWT token to a payload.
        :param token: The JWT token to decode.
        :return: The decoded payload.
        """
        try:
            return jwt.decode(token, self.__key, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            raise JwtInvalidError("Token has expired")
        except jwt.InvalidTokenError:
            raise JwtExpiredError("Invalid token")
