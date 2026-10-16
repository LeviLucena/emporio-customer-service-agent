# Example: Price lookup, active vs expired promotion

*Simulated date/time: 2026-02-20 10:00 (Campo Grande). Model: `gpt-oss:120b-cloud`.*

**What this demonstrates:** Price check (grounded in data), active promotion shown with original price, expired promotion not offered, PIX discount not stacked on promotional price.

**Customer:** Quanto custa o Takamine GD20?

<details><summary>Tool calls</summary>

- `get_product_details({"name": "Takamine GD20"})`
  ```json
  {"product_id": 95, "name": "Takamine GD20 Dreadnought Natural", "category": "Violões", "list_price": "R$ 2.199,00", "availability": "in_stock", "pix_price": "R$ 2.089,05", "description": "Violão dreadnought Takamine com tampo sólido em cedro. Excelente para fingerstyle com timbre quente e definido.", "specs": {"top": "Cedro Sólido", "back_sides": "Sapele", "neck": "Mogno", "strings": "steel", "scale": "650mm", "electronics": "no", "color": "Natural"}, "expired_promotions": {"items": ["Oferta Especial (12%)"], "note": "ENDED - never offer these; say they are over and quote the current price"}}
  ```

</details>

**Tom:** Takamine GD20 Dreadnought Natural – **R$ 2.199,00** (preço à vista).  
Se pagar via PIX sai por **R$ 2.089,05**.

Qualquer outra dúvida ou quiser saber mais opções, é só falar!

---

**Customer:** E o Taylor 110e, tem alguma promoção? Se eu pagar no PIX ainda ganho os 5%?

<details><summary>Tool calls</summary>

- `get_product_details({"name": "Taylor 110e"})`
  ```json
  {"product_id": 94, "name": "Taylor 110e Dreadnought Natural", "category": "Violões", "list_price": "R$ 5.999,00", "availability": "in_stock", "promotion": {"name": "Desconto Exclusivo", "discount_percent": 8.0, "original_price": "R$ 5.999,00", "promotional_price": "R$ 5.519,08"}, "pix_discount": "not applicable (PIX 5% does not stack on promotional prices)", "description": "Violão dreadnought Taylor com tampo sólido em Sitka Spruce e eletrônica ES2. Perfeito para palco com som amplificado de alta fidelidade.", "specs": {"top": "Sitka Spruce Sólido", "back_sides": "Walnut", "neck": "Tropical Mahogany", "strings": "steel", "scale": "648mm", "electronics": "yes", "color": "Natural"}}
  ```

</details>

**Tom:** Taylor 110e Dreadnought Natural – **R$ 5.999,00** (preço normal).  
Tem promoção “Desconto Exclusivo” de **8 %**, ficando **R$ 5.519,08**.

A promoção já está aplicada, então o desconto de 5 % do PIX **não se soma** ao preço promocional. Se pagar via PIX o valor será o mesmo **R$ 5.519,08**.

Precisa de mais alguma informação ou quer comparar com outro modelo?

---

**Customer:** Vi que o Martin D-28 estava em promoção de Páscoa, ainda tá valendo?

<details><summary>Tool calls</summary>

- `get_product_details({"name": "Martin D-28"})`
  ```json
  {"product_id": 93, "name": "Martin D-28 Dreadnought Natural", "category": "Violões", "list_price": "R$ 11.499,00", "availability": "in_stock", "pix_price": "R$ 10.924,05", "stock_note": "only 2 unit(s) left", "description": "Lendário violão Martin D-28 com tampo sólido em Sitka Spruce e fundo em Rosewood. Referência mundial em sonoridade e construção.", "specs": {"top": "Sitka Spruce Sólido", "back_sides": "East Indian Rosewood", "neck": "Select Hardwood", "strings": "steel", "scale": "645mm", "electronics": "no", "color": "Natural"}, "expired_promotions": {"items": ["Promoção de Páscoa (15%)", "Promoção de Páscoa (10%)"], "note": "ENDED - never offer these; say they are over and quote the c …
  ```

</details>

**Tom:** Martin D‑28 Dreadnought Natural – **R$ 11.499,00** (preço atual).  
No PIX sai por **R$ 10.924,05**.

A promoção de Páscoa (15 %/10 %) já terminou, então o preço que temos agora é esse. Precisa de mais alguma coisa? 🎸

---
