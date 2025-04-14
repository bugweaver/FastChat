from pydantic import conint

ChatID = conint(gt=0)
UserID = conint(gt=0)
