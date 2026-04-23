from src.core.data import init_db, sync_all_stocks
import os

if __name__ == "__main__":
    if not os.path.exists('data'):
        os.makedirs('data')
    
    print("Initialiserar databas...")
    init_db()
    
    print("Startar nedladdning av 5 års historik för alla aktier...")
    print("Detta kan ta 5-10 minuter pga Yahoo Finance rate limits.")
    
    count = sync_all_stocks()
    
    print(f"\nKLART! Laddade ner data för {count} instrument.")
    print("Du kan nu starta portalen med 'python3 app.py'.")
