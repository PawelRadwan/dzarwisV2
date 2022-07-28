#plik definujcy zmienne globalne domu 
from dataclasses import dataclass

@dataclass
class DO:
    # data klasa opisująca wyjcie
    card_num: int
    out_num_hw: int
    out_num_sw: int
    nazwa : str
    
@dataclass
class PLC:
    ip = '192.168.8.5'
    port = 502
    uid = 1
    # wyjścia wago są dostępne na holdingach w przestrzni adresowej 512-767
    out_start_reg = 512
    out_stop_reg = 767
    Douts = [
        DO(1,1,0,'swiatlo lazienka'),
        DO(1,2,1,'swiatlo biuro'),
        DO(0,0,2,'swiatlo kuchnia'),
        DO(0,0,3,'swiatlo salon'),
        DO(0,0,4,'swiatlo hol'),
        DO(0,0,5,'swiatlo spizarnia'),
        DO(0,0,6,'swiatlo jadalnia'),
        DO(0,0,7,'swiatlo Natka'),
        DO(0,0,8,'swiatlo Ola'),
        DO(0,0,9,'swiatlo Pawel'),
        DO(0,0,10,'swiatlo pralnia'),
        DO(0,0,11,'swiatlo nad schodami'),
        DO(0,0,12,'swiatlo sypialnia'),
        DO(0,0,13,'swiatlo salon kinkiety'),
        DO(0,0,14,'swiatlo wiatrolap'),
        DO(0,0,15,'swiatlo Natka 2'),
        DO(0,0,16,'lampa 17'),
        DO(0,0,17,'przejscie')




        ]



