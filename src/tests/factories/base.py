from factory.alchemy import SQLAlchemyModelFactory


class AsyncSQLAlchemyModelFactory(SQLAlchemyModelFactory):
    """Base class for all SQLAlchemy async factories"""

    class Meta:
        abstract = True
        sqlalchemy_session = None
        sqlalchemy_session_persistence = None

    @classmethod
    async def create_async(cls, session, **kwargs):
        """Asynchronously creates an instance of a model."""
        cls._meta.sqlalchemy_session = session
        obj = cls(**kwargs)
        session.add(obj)
        await session.flush()
        await session.refresh(obj)
        return obj

    @classmethod
    async def create_batch_async(cls, session, size, **kwargs):
        """Asynchronously creates multiple model instances."""
        cls._meta.sqlalchemy_session = session
        objs = []
        for _ in range(size):
            obj = cls(**kwargs)
            objs.append(obj)
        session.add_all(objs)
        await session.flush()
        for obj in objs:
            await session.refresh(obj)
        return objs
