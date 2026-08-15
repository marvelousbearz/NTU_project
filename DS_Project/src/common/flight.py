class flight:
    # 将参数存储到类内
    def __init__(self,flight_id, source, destination, hour, minute, price, seats):
        self.flight_id=flight_id
        self.source=source
        self.destination=destination
        self.hour=hour
        self.minute=minute
        self.price=price
        self.seats=seats

    # 返回可读字符串
    def _str_(self):
        return (f"Flight {self.flight_id}:{self.source} to {self.destination}\n"
                f"Departure time is {self.hour}:{self.minute}\n"
                f"Price is ${self.price}"
                f"Number of remaining seats is {self.seats}")

    # 把航班对象打包成字节数组
    def to_bytes(self):
        import struct
        source_bytes=self.source.encode('utf-8')
        dest_bytes=self.destination.encode('utf-8')

        packed=struct.pack(
            '!IH{}sH{}sBBdI'.format(len(source_bytes),len(dest_bytes)),
            self.flight_id,
            len(source_bytes),source_bytes,
            len(dest_bytes),dest_bytes,
            self.hour,self.minute,self.price,self.seats
        )
        return packed

    # to_bytes的逆操作
    @classmethod
    def from_bytes(cls,data,offset):
        flight_id,offset=unpack_int(data,offset)
        source,offset=unpack_string(data,offset)
        destination,offset=unpack_string(data,offset)
        hour,offset=unpack_bytes(data,offset)
        minute,offset=unpack_bytes(data,offset)
        price,offset=unpack_double(data,offset)
        seats,offset=unpack_int(data,offset)
        return cls(flight_id,source,destination,hour,minute,price,seats),offset




    

    