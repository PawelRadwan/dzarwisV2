#plik definujcy zmienne globalne domu 
from dataclasses import dataclass

@dataclass
class DO:
    # data klasa opisująca wyjcie
    card_num: int
    out_num_hw: int
    out_num_sw: int
    opis_funkcjonalnosci : str
    


#wyspa wago 
wago_ip  =  '192.168.8.5'
wago_mb_port = 502
wago_u_id = 1

# wyjscia 
wyjscia = [
     DO(1,1,0,'swiatlo lazienka'),
     DO(1,2,1,'swiatlo biuro')
     ]

