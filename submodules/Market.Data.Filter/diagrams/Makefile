gen:
	@echo "Generating diagrams"	
	plantuml -tpng -o ${PWD}/out *.plantuml

FILES=$(shell ls out/*.png)
files:
	@echo "Generating README.md"
	@rm README.md;
	@for file in ${FILES}; do \
		echo $$file | sed 's;out\/;;g' | sed 's;\.png;;g' | xargs -I{} echo "[{}]: ./out/{}.png" >> README.md; \
	done
